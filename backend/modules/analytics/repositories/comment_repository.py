"""Доступ к данным комментариев и их LLM-разметки.

В этом репозитории живут наиболее объёмные SQL-выборки аналитики
(агрегаты для /summary, признаки для пересборки снапшота). Чтобы он
не разрастался, методы группируются по сценариям использования:
аггрегации для summary, и выборки комментариев для пересборки.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import Row, String, bindparam, case, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.db.comment_analysis import CommentAnalysis
from backend.db.comment_pains import CommentPain
from backend.db.comments import Comment
from backend.db.enums import RelevanceEnum, SentimentEnum
from backend.db.public_social_links import PublicSocialLink
from backend.db.publics import Public
from backend.db.publications import Publication
from backend.db.regions import Region
from backend.db.users import User
from backend.modules.analytics.constants import (
    ANALYTICS_NETWORK_CODES,
    APPEAL_MESSAGE_TYPES,
)
from backend.modules.analytics.utils.public_link_filter import (
    PublicSocialLinkFilter,
    apply_public_social_link_filter,
    normalize_public_social_link_ids,
)
from backend.modules.analytics.utils.municipality_filter import (
    apply_address_municipality_filter,
    apply_comment_municipality_filter,
)
from backend.modules.analytics.utils.comment_examples import vk_comment_url

# чип для комментов с пустой подкатегорией; по нему же фильтруется список
NO_SUBCATEGORY_TITLE = "Без подкатегории"


class CommentRepository:
    """SQL-доступ к ``Comment`` и ``CommentAnalysis``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def _org_comment_count_stmt(self, user: User):
        """Базовый ``count(Comment)`` по неудалённым комментариям организации."""

        return (
            select(func.count(Comment.id))
            .select_from(Comment)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
            .where(Comment.is_deleted.is_(False))
        )

    async def count_org_comments(self, user: User, *, since: datetime | None = None) -> int:
        """Число неудалённых комментариев организации (опц. созданных после ``since``)."""

        stmt = self._org_comment_count_stmt(user)
        if since is not None:
            stmt = stmt.where(Comment.created_at > since)
        return int((await self._db.execute(stmt)).scalar() or 0)

    async def count_unanalyzed_comments(self, user: User) -> int:
        """Число комментариев организации без записи ``CommentAnalysis`` (pending)."""

        stmt = (
            self._org_comment_count_stmt(user)
            .outerjoin(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .where(CommentAnalysis.comment_id.is_(None))
        )
        return int((await self._db.execute(stmt)).scalar() or 0)

    async def sla_stats(
        self,
        user: User,
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
        sla_hours: float = 48.0,
    ) -> dict:
        """SLA ответа организации: доля обращений с официальным ответом и время до ответа.

        Обращение — как в /summary и «Топ категорий» (``APPEAL_MESSAGE_TYPES``).
        Официальный ответ — reply с ``is_official_response``; время = ответ − обращение.
        """

        link_ids = normalize_public_social_link_ids(link_id)
        complaints_link_clause = "AND psl.id IN :complaints_link_ids" if link_ids else ""
        official_link_clause = "AND psl.id IN :official_link_ids" if link_ids else ""
        municipality_clause = """
                  AND (
                      CAST(:municipality_pattern AS text) IS NULL
                      OR (
                          (
                              coalesce(json_extract_path_text(ca.entities,'address'), '') <> ''
                              OR coalesce(json_extract_path_text(ca.hierarchy,'case'), '') <> ''
                              OR json_extract_path(ca.entities,'address_hierarchy') IS NOT NULL
                          )
                          AND replace(lower(concat_ws(
                              ' ',
                              json_extract_path_text(ca.entities,'address_hierarchy','municipality'),
                              json_extract_path_text(ca.entities,'address_hierarchy','district'),
                              json_extract_path_text(ca.entities,'address_hierarchy','locality'),
                              json_extract_path_text(ca.entities,'address'),
                              json_extract_path_text(ca.hierarchy,'case')
                          )), 'ё', 'е') ~ CAST(:municipality_pattern AS text)
                      )
                      OR (
                          coalesce(json_extract_path_text(ca.entities,'address'), '') = ''
                          AND coalesce(json_extract_path_text(ca.hierarchy,'case'), '') = ''
                          AND json_extract_path(ca.entities,'address_hierarchy') IS NULL
                          AND replace(lower(coalesce(p.municipality_name, '')), 'ё', 'е') ~ CAST(:municipality_pattern AS text)
                      )
                  )
        """
        official_municipality_clause = municipality_clause.replace("ca.", "ca.").replace(":municipality_pattern", ":official_municipality_pattern")
        sql = text(
            f"""
            WITH complaints AS (
                SELECT c.id, c.comment_date
                FROM comments c
                JOIN comment_analysis ca ON ca.comment_id = c.id
                JOIN publications pub ON pub.id = c.publication_id
                JOIN public_social_links psl ON psl.id = pub.public_social_link_id
                JOIN social_networks sn ON sn.id = psl.social_network_id
                JOIN publics p ON p.id = psl.public_id
                WHERE p.organization_id = :org
                  AND c.is_deleted = false
                  AND sn.code = ANY(:networks)
                  AND ca.classification_state = 'done'
                  AND ca.relevance = 'relevant'
                  AND ca.message_type = ANY(:appeal_types)
                  AND COALESCE(ca.is_official_response, false) = false
                  AND (c.author_external_id IS NULL OR c.author_external_id NOT LIKE '-%')
                  AND (CAST(:since AS timestamptz) IS NULL OR COALESCE(c.comment_date, c.created_at) >= CAST(:since AS timestamptz))
                  {complaints_link_clause}
                  {municipality_clause}
            ),
            paired AS (
                SELECT
                    (r.r_date IS NOT NULL) AS answered,
                    CASE WHEN r.r_date IS NOT NULL AND cpl.comment_date IS NOT NULL
                              AND r.r_date >= cpl.comment_date
                         THEN EXTRACT(EPOCH FROM (r.r_date - cpl.comment_date)) / 3600.0
                    END AS gap_h
                FROM complaints cpl
                CROSS JOIN LATERAL (
                    SELECT MIN(rr.comment_date) AS r_date
                    FROM comments rr
                    JOIN comment_analysis ra ON ra.comment_id = rr.id
                    WHERE rr.parent_comment_id = cpl.id
                      AND rr.is_deleted = false
                      AND ra.is_official_response = true
                      AND length(regexp_replace(
                          regexp_replace(coalesce(rr.text, ''),
                              '\\[(id|club|public|event)[0-9]+\\|[^\\]]+\\]', '', 'gi'),
                          '[[:space:][:punct:]]+', '', 'g'
                      )) > 0
                ) r
            ),
            official AS (
                SELECT count(*) AS n
                FROM comments c
                JOIN comment_analysis ca ON ca.comment_id = c.id
                JOIN publications pub ON pub.id = c.publication_id
                JOIN public_social_links psl ON psl.id = pub.public_social_link_id
                JOIN publics p ON p.id = psl.public_id
                WHERE p.organization_id = :org
                  AND c.is_deleted = false
                  AND ca.is_official_response = true
                  AND (CAST(:since AS timestamptz) IS NULL OR COALESCE(c.comment_date, c.created_at) >= CAST(:since AS timestamptz))
                  AND length(regexp_replace(
                      regexp_replace(coalesce(c.text, ''),
                          '\\[(id|club|public|event)[0-9]+\\|[^\\]]+\\]', '', 'gi'),
                      '[[:space:][:punct:]]+', '', 'g'
                  )) > 0
                  {official_link_clause}
                  {official_municipality_clause}
            )
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE answered) AS answered,
                ROUND(AVG(gap_h)::numeric, 1) AS avg_h,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY gap_h)::numeric, 1) AS median_h,
                COUNT(*) FILTER (WHERE gap_h IS NOT NULL AND gap_h <= :sla_h) AS within_sla,
                (SELECT n FROM official) AS official_total
            FROM paired
            """
        )
        params = {
            "org": user.organization_id,
            "since": since,
            "sla_h": sla_hours,
            "networks": list(ANALYTICS_NETWORK_CODES),
            "appeal_types": list(APPEAL_MESSAGE_TYPES),
            "municipality_pattern": None,
            "official_municipality_pattern": None,
        }
        if municipality_name:
            from backend.modules.analytics.utils.municipality_filter import raw_municipality_params

            muni_params = raw_municipality_params(municipality_name)
            params["municipality_pattern"] = muni_params["municipality_pattern"]
            params["official_municipality_pattern"] = muni_params["municipality_pattern"]
        if link_ids:
            sql = sql.bindparams(
                bindparam("complaints_link_ids", expanding=True),
                bindparam("official_link_ids", expanding=True),
            )
            params["complaints_link_ids"] = link_ids
            params["official_link_ids"] = link_ids
        row = (await self._db.execute(sql, params)).fetchone()

        total = int(row.total or 0)
        answered = int(row.answered or 0)
        within = int(row.within_sla or 0)
        return {
            "appeals": total,
            "answered": answered,
            "response_rate": round(answered / total * 100, 1) if total else 0.0,
            "median_hours": float(row.median_h) if row.median_h is not None else None,
            "avg_hours": float(row.avg_h) if row.avg_h is not None else None,
            "within_sla_rate": round(within / answered * 100, 1) if answered else 0.0,
            "sla_hours": sla_hours,
            "official_total": int(row.official_total or 0),
        }

    async def list_pain_comments_page(
        self,
        *,
        pain_id: uuid.UUID,
        link_id: PublicSocialLinkFilter = None,
        subcategory: str | None = None,
        since: datetime | None = None,
        municipality_name: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[int, Sequence[Row]]:
        """Страница комментариев боли: ``(total, rows)`` без сборки DTO.

        Фильтры: площадка (``link_id``), подкатегория из ``hierarchy``, период (``since``).
        """

        ResponseComment = aliased(Comment)
        ResponseAnalysis = aliased(CommentAnalysis)
        response_at = func.coalesce(ResponseComment.comment_date, ResponseComment.created_at)
        response_without_vk_mentions = func.regexp_replace(
            func.coalesce(ResponseComment.text, ""),
            r"\[(id|club|public|event)[0-9]+\|[^\]]+\]",
            "",
            "gi",
        )
        # Не показываем как ответ один тег VK наподобие ``[id123|Надежда],``.
        response_has_content = func.length(
            func.regexp_replace(response_without_vk_mentions, r"[[:space:][:punct:]]+", "", "g")
        ) > 0

        def official_response_scalar(column):
            return (
                select(column)
                .select_from(ResponseComment)
                .join(ResponseAnalysis, ResponseAnalysis.comment_id == ResponseComment.id)
                .where(ResponseComment.parent_comment_id == Comment.id)
                .where(ResponseComment.is_deleted.is_(False))
                .where(ResponseAnalysis.is_official_response.is_(True))
                .where(response_has_content)
                .order_by(response_at.asc().nulls_last())
                .limit(1)
                .correlate(Comment)
                .scalar_subquery()
            )

        base = (
            select(
                Comment.id,
                Comment.text,
                Comment.external_id,
                Comment.comment_date,
                Publication.url.label("publication_url"),
                CommentAnalysis.sentiment,
                CommentAnalysis.message_type,
                CommentAnalysis.is_official_response,
                official_response_scalar(ResponseComment.id).label("official_response_id"),
                official_response_scalar(ResponseComment.text).label("official_response_text"),
                official_response_scalar(ResponseComment.external_id).label("official_response_external_id"),
                official_response_scalar(ResponseComment.comment_date).label("official_response_date"),
            )
            .select_from(CommentPain)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .join(Publication, Publication.id == Comment.publication_id, isouter=True)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .where(CommentPain.pain_id == pain_id)
            .where(Comment.is_deleted.is_(False))
        )
        base = self.appeal_scope(base)
        base = apply_public_social_link_filter(
            base,
            Publication.public_social_link_id,
            link_id,
        )
        base = apply_comment_municipality_filter(base, municipality_name)
        if since is not None:
            base = base.where(func.coalesce(Comment.comment_date, Comment.created_at) >= since)
        if subcategory:
            sub_expr = func.lower(func.coalesce(
                func.json_extract_path_text(CommentAnalysis.hierarchy, "subcategory"), ""
            ))
            if subcategory.lower() == NO_SUBCATEGORY_TITLE.lower():
                base = base.where(sub_expr == "")
            else:
                base = base.where(sub_expr == subcategory.lower())

        total = int(
            (await self._db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
        )
        rows = await self._db.execute(
            base.order_by(Comment.comment_date.desc().nulls_last()).offset(offset).limit(limit)
        )
        return total, rows.all()

    async def count_pain_comment_subcategories(
        self,
        *,
        pain_id: uuid.UUID,
        link_id: PublicSocialLinkFilter = None,
        since: datetime | None = None,
        municipality_name: str | None = None,
    ) -> dict[str, int]:
        """Живой счётчик комментов боли по подкатегориям (тот же базис, что и список)."""

        sub = func.lower(func.coalesce(
            func.json_extract_path_text(CommentAnalysis.hierarchy, "subcategory"), ""
        ))
        stmt = self.appeal_scope(
            select(sub.label("sub"), func.count(func.distinct(Comment.id)).label("cnt"))
            .select_from(CommentPain)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .where(CommentPain.pain_id == pain_id)
            .where(Comment.is_deleted.is_(False))
        )
        stmt = apply_public_social_link_filter(
            stmt,
            Publication.public_social_link_id,
            link_id,
        )
        stmt = apply_comment_municipality_filter(stmt, municipality_name)
        if since is not None:
            stmt = stmt.where(func.coalesce(Comment.comment_date, Comment.created_at) >= since)
        stmt = stmt.group_by(sub)
        rows = await self._db.execute(stmt)
        # пустая подкатегория — под ключом ""
        return {str(row.sub): int(row.cnt) for row in rows}

    async def list_case_counts_by_pain(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> list[Row]:
        """Живые адресные кейсы по болям из comment_analysis.hierarchy.case.

        Карта болей строится из этого же поля, поэтому карточки не должны брать
        адреса из snapshot.raw_payload: snapshot может содержать только пару
        старых/странных кейсов, пока в БД уже есть много адресных комментариев.
        """

        if not pain_ids:
            return []

        case_expr = func.json_extract_path_text(CommentAnalysis.hierarchy, "case")
        address_expr = func.json_extract_path_text(CommentAnalysis.entities, "address")
        address_hierarchy_expr = cast(
            func.json_extract_path(CommentAnalysis.entities, "address_hierarchy"),
            String,
        )
        at = func.coalesce(Comment.comment_date, Comment.created_at)
        mention_key = func.concat(
            cast(Publication.id, String),
            ":",
            func.coalesce(Comment.external_id, cast(Comment.id, String)),
        )
        latest_comment_expr = func.array_agg(
            aggregate_order_by(Comment.text, at.desc().nulls_last())
        )[1]
        latest_address_expr = func.array_agg(
            aggregate_order_by(address_expr, at.desc().nulls_last())
        )[1]
        latest_address_hierarchy_expr = func.array_agg(
            aggregate_order_by(address_hierarchy_expr, at.desc().nulls_last())
        )[1]
        stmt = (
            select(
                CommentPain.pain_id,
                case_expr.label("case_name"),
                func.coalesce(Region.name, "").label("public_region"),
                func.coalesce(Public.name, "").label("public_name"),
                func.coalesce(PublicSocialLink.title, "").label("source_title"),
                latest_comment_expr.label("sample_comment"),
                latest_address_expr.label("sample_address"),
                latest_address_hierarchy_expr.label("sample_address_hierarchy"),
                func.count(func.distinct(mention_key)).label("mentions_count"),
            )
            .select_from(CommentPain)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .outerjoin(Region, Region.id == Public.region_id)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .where(CommentPain.pain_id.in_(pain_ids))
            .where(Comment.is_deleted.is_(False))
            .where(func.coalesce(case_expr, "") != "")
        )
        stmt = self.appeal_scope(stmt)
        if since is not None:
            stmt = stmt.where(at >= since)
        stmt = apply_public_social_link_filter(
            stmt,
            Publication.public_social_link_id,
            link_id,
        )
        stmt = apply_address_municipality_filter(stmt, municipality_name)

        stmt = (
            stmt.group_by(
                CommentPain.pain_id,
                case_expr,
                Region.name,
                Public.name,
                PublicSocialLink.title,
            )
            .order_by(CommentPain.pain_id, func.count(func.distinct(mention_key)).desc())
        )
        return list((await self._db.execute(stmt)).all())

    async def list_burning_cases(
        self,
        user: User,
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
        limit: int = 40,
    ) -> list[Row]:
        """Адреса с негативом и признаком, отвечала ли по ним власть.

        Отдельный запрос, а не расширение ``list_case_counts_by_pain``: тот
        лежит на пути списка болей, и коррелированный подзапрос про ответы
        замедлил бы каждую карточку ради одного блока в отчёте.
        """

        case_expr = func.json_extract_path_text(CommentAnalysis.hierarchy, "case")
        at = func.coalesce(Comment.comment_date, Comment.created_at)
        mention_key = func.concat(
            cast(Publication.id, String),
            ":",
            func.coalesce(Comment.external_id, cast(Comment.id, String)),
        )
        reply = aliased(Comment)
        reply_analysis = aliased(CommentAnalysis)
        # Ответ засчитывается тот же, что в SLA: официальный непустой reply.
        answered_expr = (
            select(1)
            .select_from(reply)
            .join(reply_analysis, reply_analysis.comment_id == reply.id)
            .where(reply.parent_comment_id == Comment.id)
            .where(reply.is_deleted.is_(False))
            .where(reply_analysis.is_official_response.is_(True))
            .exists()
        )
        negative_key = case(
            (CommentAnalysis.sentiment == SentimentEnum.negative, mention_key)
        )
        answered_key = case((answered_expr, mention_key))

        stmt = (
            select(
                case_expr.label("case_name"),
                func.coalesce(Region.name, "").label("public_region"),
                func.coalesce(Public.name, "").label("public_name"),
                func.coalesce(PublicSocialLink.title, "").label("source_title"),
                func.count(func.distinct(mention_key)).label("mentions_count"),
                func.count(func.distinct(negative_key)).label("negative_count"),
                func.count(func.distinct(answered_key)).label("answered_count"),
            )
            .select_from(Comment)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .outerjoin(Region, Region.id == Public.region_id)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .where(Public.organization_id == user.organization_id)
            .where(Comment.is_deleted.is_(False))
            .where(func.coalesce(case_expr, "") != "")
        )
        stmt = self.appeal_scope(stmt)
        if since is not None:
            stmt = stmt.where(at >= since)
        stmt = apply_public_social_link_filter(stmt, Publication.public_social_link_id, link_id)
        stmt = apply_address_municipality_filter(stmt, municipality_name)
        stmt = (
            stmt.group_by(case_expr, Region.name, Public.name, PublicSocialLink.title)
            .order_by(func.count(func.distinct(negative_key)).desc())
            .limit(limit)
        )
        return list((await self._db.execute(stmt)).all())

    async def list_case_rows_for_pain(
        self,
        pain_id: uuid.UUID,
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> list[Row]:
        """Адресные кейсы боли для карточки; по подкатегориям их группируют позже."""

        case_expr = func.json_extract_path_text(CommentAnalysis.hierarchy, "case")
        subcategory_expr = func.json_extract_path_text(CommentAnalysis.hierarchy, "subcategory")
        address_expr = func.json_extract_path_text(CommentAnalysis.entities, "address")
        address_hierarchy_expr = cast(
            func.json_extract_path(CommentAnalysis.entities, "address_hierarchy"),
            String,
        )
        at = func.coalesce(Comment.comment_date, Comment.created_at)
        stmt = (
            select(
                subcategory_expr.label("subcategory"),
                case_expr.label("case_name"),
                func.coalesce(Region.name, "").label("public_region"),
                func.coalesce(Public.name, "").label("public_name"),
                func.coalesce(PublicSocialLink.title, "").label("source_title"),
                address_expr.label("address"),
                address_hierarchy_expr.label("address_hierarchy"),
                Comment.id.label("comment_id"),
                Comment.text,
                Comment.external_id,
                Comment.comment_date,
                Publication.id.label("publication_id"),
                Publication.url.label("publication_url"),
                CommentAnalysis.sentiment,
                CommentAnalysis.message_type,
            )
            .select_from(CommentPain)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .outerjoin(Region, Region.id == Public.region_id)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .where(CommentPain.pain_id == pain_id)
            .where(Comment.is_deleted.is_(False))
            .where(func.coalesce(case_expr, "") != "")
        )
        stmt = self.appeal_scope(stmt)
        if since is not None:
            stmt = stmt.where(at >= since)
        stmt = apply_public_social_link_filter(
            stmt,
            Publication.public_social_link_id,
            link_id,
        )
        stmt = apply_address_municipality_filter(stmt, municipality_name)

        stmt = stmt.order_by(
            subcategory_expr.asc().nulls_last(),
            case_expr.asc(),
            at.desc().nulls_last(),
        )
        return list((await self._db.execute(stmt)).all())

    async def count_pain_comments_between(
        self,
        pain_id: uuid.UUID,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        """Число уникальных комментариев боли с датой коммента в ``[start, end)``."""

        at = func.coalesce(Comment.comment_date, Comment.created_at)
        stmt = (
            select(func.count(func.distinct(CommentPain.comment_id)))
            .select_from(CommentPain)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .where(CommentPain.pain_id == pain_id)
        )
        if start is not None:
            stmt = stmt.where(at >= start)
        if end is not None:
            stmt = stmt.where(at < end)
        return int((await self._db.execute(stmt)).scalar() or 0)

    async def count_comments_since_by_pains(
        self,
        pain_ids: list[uuid.UUID],
        *,
        start: datetime,
    ) -> dict[uuid.UUID, int]:
        """Число уникальных комментариев с датой коммента ``>= start`` по каждой боли."""

        if not pain_ids:
            return {}
        rows = await self._db.execute(
            select(CommentPain.pain_id, func.count(func.distinct(CommentPain.comment_id)))
            .select_from(CommentPain)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .where(CommentPain.pain_id.in_(pain_ids))
            .where(func.coalesce(Comment.comment_date, Comment.created_at) >= start)
            .group_by(CommentPain.pain_id)
        )
        return {pain_id: int(count) for pain_id, count in rows.all()}

    async def signal_counts_rows_for_pain(
        self,
        pain_id: uuid.UUID,
        link_id: PublicSocialLinkFilter = None,
        *,
        since: datetime | None = None,
        municipality_name: str | None = None,
    ) -> Sequence[Row]:
        """Сгруппированные ``(sentiment, message_type, count)`` боли (опц. площадка/период)."""

        stmt = (
            select(
                CommentAnalysis.sentiment,
                CommentAnalysis.message_type,
                func.count(func.distinct(CommentAnalysis.comment_id)),
            )
            .select_from(CommentPain)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .where(CommentPain.pain_id == pain_id)
            .where(Comment.is_deleted.is_(False))
            .group_by(CommentAnalysis.sentiment, CommentAnalysis.message_type)
        )
        stmt = apply_public_social_link_filter(
            stmt,
            Publication.public_social_link_id,
            link_id,
        )
        stmt = apply_comment_municipality_filter(stmt, municipality_name)
        if since is not None:
            stmt = stmt.where(func.coalesce(Comment.comment_date, Comment.created_at) >= since)
        result = await self._db.execute(stmt)
        return result.all()

    @staticmethod
    def appeal_scope(stmt):
        """Фильтр обращения: тот же, что у /summary, SLA и «Топ категорий».

        Требует, чтобы ``CommentAnalysis`` уже был приджойнен. Без него срезы
        болей считали и оффтоп, и ответы организаций — «упоминаний» выходило
        больше, чем всего обращений в периоде.
        """

        return (
            stmt
            .where(CommentAnalysis.classification_state == "done")
            .where(CommentAnalysis.relevance == RelevanceEnum.relevant)
            .where(CommentAnalysis.message_type.in_(APPEAL_MESSAGE_TYPES))
            .where(func.coalesce(CommentAnalysis.is_official_response, False).is_(False))
            .where(or_(
                Comment.author_external_id.is_(None),
                ~Comment.author_external_id.like("-%"),
            ))
        )

    @classmethod
    def _pain_slice_base(
        cls,
        pain_ids: list[uuid.UUID],
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ):
        """Базовый query CommentPain → Comment → Publication для срезов болей."""

        stmt = cls.appeal_scope(
            select(CommentPain)
            .select_from(CommentPain)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .where(CommentPain.pain_id.in_(pain_ids))
            .where(Comment.is_deleted.is_(False))
        )
        if since is not None:
            # период — по реальной дате коммента в VK, не по времени импорта
            stmt = stmt.where(
                func.coalesce(Comment.comment_date, Comment.created_at) >= since
            )
        stmt = apply_public_social_link_filter(
            stmt,
            Publication.public_social_link_id,
            link_id,
        )
        return apply_comment_municipality_filter(stmt, municipality_name)

    async def count_mentions_by_pain(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> dict[str, int]:
        """Число уникальных комментариев по каждой боли в фильтре."""

        if not pain_ids:
            return {}
        stmt = self._pain_slice_base(
            pain_ids,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        rows = await self._db.execute(
            stmt.with_only_columns(
                CommentPain.pain_id,
                func.count(func.distinct(CommentPain.comment_id)),
            ).group_by(CommentPain.pain_id)
        )
        return {str(pid): int(count) for pid, count in rows.all()}

    async def count_publications_by_pain(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> dict[str, int]:
        """Число публикаций с комментариями по каждой боли в фильтре."""

        if not pain_ids:
            return {}
        stmt = self._pain_slice_base(
            pain_ids,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        rows = await self._db.execute(
            stmt.with_only_columns(
                CommentPain.pain_id,
                func.count(func.distinct(Comment.publication_id)),
            ).group_by(CommentPain.pain_id)
        )
        return {str(pid): int(count) for pid, count in rows.all()}

    async def collect_comment_ids_by_pain(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> dict[str, set[str]]:
        """Видимые comment_id по каждой боли в текущем фильтре.

        Период тоже сужает выборку: снапшот хранит примеры за всё время, и без
        этого в недельный отчёт попадали комментарии из других месяцев.
        """

        if not pain_ids or (link_id is None and municipality_name is None and since is None):
            return {}
        stmt = self._pain_slice_base(
            pain_ids,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        rows = await self._db.execute(
            stmt.with_only_columns(CommentPain.pain_id, CommentPain.comment_id)
        )
        out: dict[str, set[str]] = {}
        for pain_id, comment_id in rows.all():
            out.setdefault(str(pain_id), set()).add(str(comment_id))
        return out

    async def list_comment_examples_by_pain(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
        limit_per_pain: int = 3,
    ) -> dict[str, list[dict[str, object]]]:
        """Свежие комментарии по каждой боли внутри текущего фильтра.

        Снапшот хранит примеры за всё время и по всем территориям. В отчёте по
        одному муниципалитету они почти все чужие, отсев по видимым id вырезал
        их подчистую, и раздел с цитатами оставался пустым. Здесь примеры
        берутся сразу под фильтр отчёта.
        """

        if not pain_ids:
            return {}

        at = func.coalesce(Comment.comment_date, Comment.created_at)
        base = self._pain_slice_base(
            pain_ids,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        ).with_only_columns(
            CommentPain.pain_id.label("pain_id"),
            Comment.text.label("text"),
            Comment.external_id.label("external_id"),
            Publication.url.label("publication_url"),
            func.row_number()
            .over(partition_by=CommentPain.pain_id, order_by=at.desc())
            .label("row_number"),
        )

        sub = base.subquery()
        rows = await self._db.execute(
            select(sub).where(sub.c.row_number <= limit_per_pain)
        )

        out: dict[str, list[dict[str, object]]] = {}
        for row in rows.all():
            text_value = str(row.text or "").strip()
            if not text_value:
                continue
            url = vk_comment_url(row.publication_url, row.external_id) or row.publication_url
            out.setdefault(str(row.pain_id), []).append({"text": text_value, "url": url or ""})
        return out

    async def recent_comments_for_pain(
        self,
        pain_id: uuid.UUID,
        link_id: PublicSocialLinkFilter,
        *,
        limit: int = 5,
    ) -> Sequence[Row]:
        """Свежие комментарии боли на площадке (сырые строки для примеров)."""

        stmt = (
            select(
                Comment.id,
                Comment.text,
                Comment.external_id,
                Publication.url.label("publication_url"),
                CommentAnalysis.message_type,
                CommentAnalysis.sentiment,
            )
            .select_from(CommentPain)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id, isouter=True)
            .where(CommentPain.pain_id == pain_id)
            .where(Comment.is_deleted.is_(False))
            .order_by(Comment.created_at.desc())
            .limit(limit)
        )
        stmt = apply_public_social_link_filter(
            stmt,
            Publication.public_social_link_id,
            link_id,
        )
        result = await self._db.execute(stmt)
        return result.all()

    async def get_existing_analysis(self, comment_id: uuid.UUID) -> CommentAnalysis | None:
        """Текущий ``CommentAnalysis`` комментария, если он уже размечен."""

        result = await self._db.execute(
            select(CommentAnalysis)
            .where(CommentAnalysis.comment_id == comment_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_comments_for_publication(
        self,
        publication_id: uuid.UUID,
        *,
        since: datetime | None = None,
    ) -> list[Comment]:
        """Комментарии публикации с опциональным фильтром по дате создания."""

        stmt = select(Comment).where(Comment.publication_id == publication_id)
        if since is not None:
            stmt = stmt.where(Comment.created_at >= since)
        result = await self._db.execute(stmt.order_by(Comment.created_at.asc()))
        return list(result.scalars().all())
