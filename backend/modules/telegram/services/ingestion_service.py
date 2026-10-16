"""Оркестрация Telegram ingest."""

from __future__ import annotations

from datetime import datetime

from backend.db.users import User
from backend.modules.telegram.client import TelegramApiClient
from backend.modules.telegram.links.link_parser import TelegramLinkParser
from backend.modules.telegram.repositories import TelegramIngestionRepository


class TelegramIngestionService:
    def __init__(self, db, *, api_client: TelegramApiClient | None = None) -> None:
        self.repository = TelegramIngestionRepository(db)
        self.api_client = api_client or TelegramApiClient()
        self.link_parser = TelegramLinkParser()

    async def ingest_link(
        self,
        user: User,
        raw_url: str,
        *,
        max_posts: int | None = None,
        fetch_comments: bool = True,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        reporter=None,
    ):
        ref = self.link_parser.parse(raw_url)
        organization = await self.repository.resolve_organization(user)
        fetched = await self.api_client.fetch(
            ref,
            max_posts=max_posts,
            date_from=date_from,
            date_to=date_to,
            fetch_comments=fetch_comments,
            reporter=reporter,
        )
        public, link = await self.repository.ensure_public_link(organization, fetched.channel)
        comments_imported = 0
        if reporter is not None:
            await reporter.update(total=len(fetched.messages), done=0, message="Сохранение постов Telegram…")
        for index, message in enumerate(fetched.messages, start=1):
            if reporter is not None:
                reporter.raise_if_cancelled()
            publication = await self.repository.upsert_publication(
                organization=organization,
                public=public,
                link=link,
                user=user,
                message=message,
            )
            if fetch_comments:
                comments_imported += await self.repository.upsert_comments(
                    publication, message.id, fetched.comments.get(message.id, [])
                )
            if reporter is not None:
                await reporter.update(done=index, message=f"Сохранение постов Telegram: {index}/{len(fetched.messages)}…")
        await self.repository.upsert_public_metric(link, fetched.channel, fetched.messages)
        await self.repository.add_ingest_audit_log(
            user=user,
            link=link,
            posts_imported=len(fetched.messages),
            comments_imported=comments_imported,
        )
        await self.repository.commit()
        return TelegramIngestResult(
            canonical_url=fetched.channel.canonical_url,
            public_id=str(public.id),
            public_social_link_id=str(link.id),
            posts_imported=len(fetched.messages),
            publications_imported=len(fetched.messages),
            comments_imported=comments_imported,
            notes=fetched.notes or None,
        )


class TelegramIngestResult:
    type = "channel"

    def __init__(
        self,
        *,
        canonical_url: str,
        public_id: str,
        public_social_link_id: str,
        posts_imported: int,
        publications_imported: int,
        comments_imported: int,
        notes: list[str] | None,
    ) -> None:
        self.canonical_url = canonical_url
        self.public_id = public_id
        self.public_social_link_id = public_social_link_id
        self.posts_imported = posts_imported
        self.publications_imported = publications_imported
        self.comments_imported = comments_imported
        self.notes = notes

