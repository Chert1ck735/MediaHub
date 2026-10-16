from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.users import User
from backend.modules.report.analyzers.dzen_analyzer import analyze_dzen
from backend.modules.report.analyzers.vk_analyzer import analyze_vk
from backend.modules.report.errors import ReportError
from backend.modules.report.loaders.csv_loader import load_dzen_data
from backend.modules.report.repositories.audience_repository import AudienceRepository
from backend.modules.report.repositories.post_repository import ReportPostRepository
from backend.modules.report.schema import (
    ReportPreviewRequest,
    ReportPreviewResponse,
    ReportTimePoint,
    ReportTopPost,
)
from backend.modules.report.services.llm_recommendations_service import generate_recommendations
from backend.modules.report.utils.numeric import safe_int
from backend.modules.analytics.utils.municipality_filter import canonicalize_municipality_filters


class ReportPreviewService:
    """Собирает данные предпросмотра отчёта, не унося логику в обработчики."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._posts = ReportPostRepository(db)
        self._audience = AudienceRepository(db)

    async def preview(self, user: User, payload: ReportPreviewRequest) -> ReportPreviewResponse:
        platform = payload.platform.lower().strip()
        if platform in ("vk", "ok", "telegram"):
            posts, stats, window, heatmap = await self._build_vk(user, payload)
        elif platform in ("dzen", "дзен"):
            posts, stats = self._build_dzen(payload)
            window, heatmap = None, None
        else:
            raise ReportError(f"Неизвестная площадка: {payload.platform}. Допустимые: vk, dzen")

        # Рекомендации (LLM) НЕ генерим здесь — preview должен быть быстрым и
        # авто-загружаться. Их тянет отдельный lazy-эндпоинт /report/recommendations.
        return self._to_response(
            payload,
            posts=posts,
            stats=stats,
            recommendations="",
            recommended_post_window=window,
            activity_heatmap=heatmap,
        )

    async def recommendations(self, user: User, payload: ReportPreviewRequest) -> str:
        """LLM-рекомендации по контенту (lazy, кэшируются) — отдельно от preview."""
        platform = payload.platform.lower().strip()
        if platform in ("vk", "ok", "telegram"):
            _, stats, _, _ = await self._build_vk(user, payload)
        elif platform in ("dzen", "дзен"):
            _, stats = self._build_dzen(payload)
        else:
            raise ReportError(f"Неизвестная площадка: {payload.platform}. Допустимые: vk, dzen")
        return generate_recommendations(stats.get("platform", payload.platform), stats)

    async def _build_vk(
        self,
        user: User,
        payload: ReportPreviewRequest,
    ) -> tuple[list[dict], dict, str | None, list[list[int]] | None]:
        if not user.organization_id:
            raise ReportError("У пользователя не назначена организация")
        municipality_name = self._municipality_filter(payload.municipality_name)

        posts = await self._posts.load_vk_posts(
            user.organization_id,
            public_social_link_id=payload.public_social_link_id,
            period=payload.period,
            municipality_name=municipality_name,
            platform=payload.platform.lower().strip(),
        )

        stats = analyze_vk(posts)
        stats["platform"] = {"vk": "VK", "ok": "Одноклассники", "telegram": "TG"}[payload.platform.lower().strip()]
        window, heatmap = await self._audience.compute_activity(
            user.organization_id,
            public_social_link_id=payload.public_social_link_id,
            period=payload.period,
            municipality_name=municipality_name,
            platform=payload.platform.lower().strip(),
        )
        return posts, stats, window, heatmap

    @staticmethod
    def _municipality_filter(value: str | None) -> str | None:
        try:
            return ",".join(canonicalize_municipality_filters(value)) or None
        except ValueError as exc:
            raise ReportError(str(exc)) from exc

    @staticmethod
    def _build_dzen(payload: ReportPreviewRequest) -> tuple[list[dict], dict]:
        posts = load_dzen_data(payload.csv_path or "dzen_posts.csv")
        if not posts:
            raise ReportError("Нет данных по Дзену")
        return posts, analyze_dzen(posts)

    @staticmethod
    def _to_response(
        payload: ReportPreviewRequest,
        *,
        posts: list[dict],
        stats: dict,
        recommendations: str,
        recommended_post_window: str | None,
        activity_heatmap: list[list[int]] | None,
    ) -> ReportPreviewResponse:
        points = [
            ReportTimePoint(
                date=p["dt"].isoformat(),
                views=int(p.get("views", 0)),
                likes=int(p.get("likes", 0)),
                comments=int(p.get("comments", 0)),
            )
            for p in (stats.get("points") or [])
        ]

        top_source = stats.get("top_by_views") or stats.get("top_by_likes") or []
        top_posts = [_to_report_post(item) for item in top_source]
        all_posts = sorted(
            [_to_report_post(post) for post in posts],
            key=lambda post: post.date or "",
        )

        return ReportPreviewResponse(
            platform=stats.get("platform", payload.platform),
            total_posts=int(stats.get("total_posts", 0)),
            avg_views=float(stats.get("avg_views", 0)),
            max_views=int(stats.get("max_views", 0)),
            avg_likes=float(stats.get("avg_likes")) if "avg_likes" in stats else None,
            max_likes=int(stats.get("max_likes")) if "max_likes" in stats else None,
            avg_comments=float(stats.get("avg_comments")) if "avg_comments" in stats else None,
            max_comments=int(stats.get("max_comments")) if "max_comments" in stats else None,
            group_members=int(stats.get("group_members")) if "group_members" in stats else None,
            channel=str(stats.get("channel")) if "channel" in stats else None,
            points=points,
            top_posts=top_posts,
            all_posts=all_posts,
            recommendations=recommendations,
            recommended_post_window=recommended_post_window,
            activity_heatmap=activity_heatmap,
        )


def _to_report_post(item: dict) -> ReportTopPost:
    return ReportTopPost(
        date=str(item.get("date")) if item.get("date") else None,
        text=(item.get("text") or "").strip(),
        views=safe_int(item.get("views")),
        likes=safe_int(item.get("likes")) if "likes" in item else None,
        comments=safe_int(item.get("comments")) if "comments" in item else None,
        url=item.get("url") or None,
    )
