from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.data_sources import DataSource
from backend.db.enums import SourceTypeEnum
from backend.db.pain_strategies import PainStrategy
from backend.db.pains import Pain
from backend.db.posts import Post
from backend.db.posts_tags import post_tags
from backend.db.strategy_posts import StrategyPost
from backend.db.tags import Tag


def _normalize_source_type(value: str | SourceTypeEnum) -> SourceTypeEnum:
    if isinstance(value, SourceTypeEnum):
        return value
    return SourceTypeEnum(value)


async def get_or_create_data_source(
    db: AsyncSession,
    *,
    source_type: str | SourceTypeEnum,
    name: str,
    description: str | None = None,
    configuration: dict[str, Any] | None = None,
) -> DataSource:
    normalized_source_type = _normalize_source_type(source_type)
    result = await db.execute(
        select(DataSource).where(
            DataSource.type == normalized_source_type,
            DataSource.name == name,
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        source = DataSource(
            type=normalized_source_type,
            name=name,
            description=description,
            configuration=configuration or {},
            is_active=True,
        )
        db.add(source)
        await db.flush()
        return source

    if description and source.description != description:
        source.description = description
    if configuration:
        merged = dict(source.configuration or {})
        merged.update(configuration)
        source.configuration = merged
    if not source.is_active:
        source.is_active = True
    return source


async def sync_post_tags(
    db: AsyncSession,
    post: Post,
    tag_names: Iterable[str],
) -> None:
    normalized = sorted(
        {
            tag.strip().lower().replace(" ", "_")
            for tag in tag_names
            if tag and tag.strip()
        }
    )

    await db.execute(delete(post_tags).where(post_tags.c.post_id == post.id))
    if not normalized:
        return

    existing = await db.execute(select(Tag).where(Tag.name.in_(normalized)))
    tags_by_name = {tag.name: tag for tag in existing.scalars().all()}

    for name in normalized:
        if name in tags_by_name:
            continue
        tag = Tag(name=name)
        db.add(tag)
        await db.flush()
        tags_by_name[name] = tag

    await db.execute(
        post_tags.insert(),
        [{"post_id": post.id, "tag_id": tags_by_name[name].id} for name in normalized],
    )


async def link_post_to_strategy(
    db: AsyncSession,
    *,
    strategy_id: str | None,
    post: Post,
) -> StrategyPost | None:
    if not strategy_id:
        return None

    result = await db.execute(
        select(PainStrategy)
        .join(Pain, Pain.id == PainStrategy.pain_id)
        .where(PainStrategy.id == strategy_id)
        .where(Pain.organization_id == post.organization_id)
    )
    strategy = result.scalar_one_or_none()
    if strategy is None:
        return None

    existing = await db.execute(
        select(StrategyPost).where(
            StrategyPost.strategy_id == strategy.id,
            StrategyPost.post_id == post.id,
        )
    )
    link = existing.scalar_one_or_none()
    if link is not None:
        return link

    link = StrategyPost(strategy_id=strategy.id, post_id=post.id)
    db.add(link)
    await db.flush()
    return link
