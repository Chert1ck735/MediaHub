"""Operational data-health summary for organization communities."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.users import User
from backend.modules.organization.services.authorization_service import AuthorizationService

FRESH_HOURS = 48
WARNING_HOURS = 24 * 7


class DataHealthService:
    """Считает свежесть данных и классификации по каждой ссылке."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._authz = AuthorizationService(db)

    async def get(self, actor: User, organization_id: uuid.UUID) -> dict[str, Any]:
        self._authz.require_organization_admin(actor, organization_id)
        rows = (await self._db.execute(text("""
            WITH links AS (
                SELECT
                    p.id AS public_id,
                    p.name AS public_name,
                    psl.id AS link_id,
                    psl.title AS link_title,
                    psl.url AS url,
                    psl.is_active AS is_active,
                    sn.code AS social_network_code,
                    sn.name AS social_network_name
                FROM publics p
                JOIN public_social_links psl ON psl.public_id = p.id
                JOIN social_networks sn ON sn.id = psl.social_network_id
                WHERE p.organization_id = :org
            ),
            post_stats AS (
                SELECT
                    pub.public_social_link_id AS link_id,
                    count(pub.id) AS posts_count,
                    max(pub.published_at) AS last_publication_at,
                    max(coalesce(pub.last_synced_at, pub.published_at, pub.created_at)) AS last_post_sync_at
                FROM publications pub
                GROUP BY pub.public_social_link_id
            ),
            comment_stats AS (
                SELECT
                    pub.public_social_link_id AS link_id,
                    count(cm.id) AS comments_count,
                    max(cm.comment_date) AS last_comment_at,
                    max(cm.parsed_at) AS last_parsed_at,
                    count(ca.id) AS analyzed_count,
                    count(ca.id) FILTER (WHERE ca.classification_state = 'done') AS classified_count,
                    count(ca.id) FILTER (WHERE ca.classification_state = 'pending') AS pending_count,
                    count(ca.id) FILTER (WHERE ca.classification_state = 'processing') AS processing_count,
                    count(ca.id) FILTER (WHERE ca.classification_state = 'failed') AS failed_count,
                    max(ca.analyzed_at) AS last_analysis_at
                FROM comments cm
                JOIN publications pub ON pub.id = cm.publication_id
                LEFT JOIN comment_analysis ca ON ca.comment_id = cm.id
                WHERE cm.is_deleted = false
                GROUP BY pub.public_social_link_id
            )
            SELECT
                links.public_id,
                links.public_name,
                links.link_id,
                links.link_title,
                links.url,
                links.is_active,
                links.social_network_code,
                links.social_network_name,
                coalesce(post_stats.posts_count, 0) AS posts_count,
                post_stats.last_publication_at,
                post_stats.last_post_sync_at,
                coalesce(comment_stats.comments_count, 0) AS comments_count,
                comment_stats.last_comment_at,
                comment_stats.last_parsed_at,
                coalesce(comment_stats.analyzed_count, 0) AS analyzed_count,
                coalesce(comment_stats.classified_count, 0) AS classified_count,
                coalesce(comment_stats.pending_count, 0) AS pending_count,
                coalesce(comment_stats.processing_count, 0) AS processing_count,
                coalesce(comment_stats.failed_count, 0) AS failed_count,
                comment_stats.last_analysis_at
            FROM links
            LEFT JOIN post_stats ON post_stats.link_id = links.link_id
            LEFT JOIN comment_stats ON comment_stats.link_id = links.link_id
            ORDER BY links.public_name ASC, links.social_network_code ASC, links.link_title ASC NULLS LAST
        """), {"org": organization_id})).mappings().all()

        items = [self._row_to_item(row) for row in rows]
        totals = self._totals(items)
        return {
            "generated_at": self._now().isoformat(),
            "thresholds": {
                "fresh_hours": FRESH_HOURS,
                "warning_hours": WARNING_HOURS,
            },
            "summary": totals,
            "items": items,
        }

    def _row_to_item(self, row: Any) -> dict[str, Any]:
        posts_count = int(row["posts_count"] or 0)
        comments_count = int(row["comments_count"] or 0)
        analyzed_count = int(row["analyzed_count"] or 0)
        classified_count = int(row["classified_count"] or 0)
        pending_count = int(row["pending_count"] or 0)
        processing_count = int(row["processing_count"] or 0)
        failed_count = int(row["failed_count"] or 0)
        missing_analysis_count = max(0, comments_count - analyzed_count)
        classification_percent = (
            round(classified_count / comments_count * 100, 1)
            if comments_count
            else 100.0
        )

        data_anchor = self._latest(
            row["last_parsed_at"],
            row["last_post_sync_at"],
            row["last_comment_at"],
            row["last_publication_at"],
        )
        data_age_hours = self._age_hours(data_anchor)
        data_status = self._data_status(posts_count, comments_count, data_age_hours)
        classification_status = self._classification_status(
            comments_count,
            missing_analysis_count,
            pending_count,
            processing_count,
            failed_count,
        )
        overall_status = self._overall_status(data_status, classification_status)

        return {
            "public_id": str(row["public_id"]),
            "public_name": row["public_name"],
            "link_id": str(row["link_id"]),
            "link_title": row["link_title"],
            "url": row["url"],
            "is_active": bool(row["is_active"]),
            "social_network_code": row["social_network_code"],
            "social_network_name": row["social_network_name"],
            "posts_count": posts_count,
            "comments_count": comments_count,
            "analyzed_count": analyzed_count,
            "classified_count": classified_count,
            "pending_count": pending_count,
            "processing_count": processing_count,
            "failed_count": failed_count,
            "missing_analysis_count": missing_analysis_count,
            "classification_percent": classification_percent,
            "last_publication_at": self._iso(row["last_publication_at"]),
            "last_post_sync_at": self._iso(row["last_post_sync_at"]),
            "last_comment_at": self._iso(row["last_comment_at"]),
            "last_parsed_at": self._iso(row["last_parsed_at"]),
            "last_analysis_at": self._iso(row["last_analysis_at"]),
            "data_age_hours": data_age_hours,
            "data_status": data_status,
            "classification_status": classification_status,
            "overall_status": overall_status,
        }

    def _totals(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        comments = sum(item["comments_count"] for item in items)
        classified = sum(item["classified_count"] for item in items)
        pending = sum(item["pending_count"] for item in items)
        processing = sum(item["processing_count"] for item in items)
        failed = sum(item["failed_count"] for item in items)
        missing = sum(item["missing_analysis_count"] for item in items)
        stale = sum(1 for item in items if item["data_status"] == "stale")
        warning = sum(1 for item in items if item["data_status"] == "warning")
        incomplete = sum(
            1 for item in items
            if item["classification_status"] in {"incomplete", "processing"}
        )
        return {
            "links_count": len(items),
            "active_links_count": sum(1 for item in items if item["is_active"]),
            "posts_count": sum(item["posts_count"] for item in items),
            "comments_count": comments,
            "classified_count": classified,
            "pending_count": pending,
            "processing_count": processing,
            "failed_count": failed,
            "missing_analysis_count": missing,
            "classification_percent": round(classified / comments * 100, 1) if comments else 100.0,
            "stale_links_count": stale,
            "warning_links_count": warning,
            "incomplete_classification_links_count": incomplete,
            "failed_classification_links_count": sum(
                1 for item in items if item["classification_status"] == "has_errors"
            ),
            "oldest_data_age_hours": max(
                (item["data_age_hours"] for item in items if item["data_age_hours"] is not None),
                default=None,
            ),
        }

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _age_hours(cls, value: datetime | None) -> float | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return round(max(0.0, (cls._now() - value).total_seconds() / 3600), 1)

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    @staticmethod
    def _latest(*values: datetime | None) -> datetime | None:
        known = [value for value in values if value is not None]
        return max(known) if known else None

    @staticmethod
    def _data_status(posts_count: int, comments_count: int, age_hours: float | None) -> str:
        if posts_count == 0 and comments_count == 0:
            return "empty"
        if age_hours is None:
            return "unknown"
        if age_hours <= FRESH_HOURS:
            return "fresh"
        if age_hours <= WARNING_HOURS:
            return "warning"
        return "stale"

    @staticmethod
    def _classification_status(
        comments_count: int,
        missing_analysis_count: int,
        pending_count: int,
        processing_count: int,
        failed_count: int,
    ) -> str:
        if comments_count == 0:
            return "no_comments"
        if failed_count > 0:
            return "has_errors"
        if processing_count > 0:
            return "processing"
        if pending_count > 0 or missing_analysis_count > 0:
            return "incomplete"
        return "complete"

    @staticmethod
    def _overall_status(data_status: str, classification_status: str) -> str:
        if data_status == "empty":
            return "empty"
        if classification_status == "has_errors":
            return "classification_errors"
        if classification_status in {"incomplete", "processing"}:
            return "classification_incomplete"
        if data_status == "stale":
            return "stale_data"
        if data_status in {"warning", "unknown"}:
            return "attention"
        return "ok"
