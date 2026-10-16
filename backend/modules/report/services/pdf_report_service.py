from __future__ import annotations

import asyncio
import functools
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.db.public_social_links import PublicSocialLink
from backend.db.publics import Public
from backend.db.social_networks import SocialNetwork

from backend.db.users import User
from backend.modules.analytics.repositories.comment_repository import CommentRepository
from backend.modules.analytics.repositories.signals_repository import SignalsRepository
from backend.modules.analytics.services.pain_list_service import PainListService
from backend.modules.analytics.services.summary_service import AnalyticsSummaryService
from backend.modules.analytics.services.pain_slice_service import PainSliceService
from backend.modules.analytics.utils.municipality_filter import canonicalize_municipality_filters
from backend.modules.analytics.utils.public_link_filter import (
    compact_public_social_link_filter,
    parse_public_social_link_ids,
)
from backend.modules.analytics.utils.time_helpers import period_to_since
from backend.modules.report.errors import ReportError
from backend.modules.report.schema import ReportGenerateRequest
from backend.modules.report.services.pdf_builder import generate_municipality_pains_pdf
from backend.modules.report.services.llm_recommendations_service import cached_recommendations
from backend.modules.report.services.report_orchestrator import (
    ReportOrchestrator,
    ReportOrchestratorDependencies,
)

logger = logging.getLogger(__name__)


# Отдельный пул под сборку отчётов: не конкурирует с фоновым LLM-воркером за
# общий default-пул, и один воркер — matplotlib/pyplot не потокобезопасен,
# параллельный рендер даёт клинч.
_REPORT_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="report")


@dataclass(frozen=True)
class PdfReportResult:
    path: str


def _link_filter(value: str | None):
    """Разбирает строку «id,id» в фильтр площадок.

    Передавать её в фильтр как есть нельзя: он считает строку
    последовательностью и разбирает по буквам — запрос падает.
    """

    return compact_public_social_link_filter(parse_public_social_link_ids(value))


class ReportPdfService:
    """Готовит данные и собирает PDF-отчёт вне HTTP-роутера."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        reports_dir: Path | str = "generated_reports",
    ) -> None:
        self._db = db
        self._reports_dir = Path(reports_dir)
        self._summary = AnalyticsSummaryService(db)
        self._pain_list = PainListService(db)
        self._comments = CommentRepository(db)
        self._signals = SignalsRepository(db)
        # PDF берёт рекомендации из кэша (без LLM), чтобы не блокировать сервер
        # на медленном/недоступном LLM.
        self._orchestrator = ReportOrchestrator(
            ReportOrchestratorDependencies(generate_recommendations=cached_recommendations)
        )

    async def generate(self, user: User, payload: ReportGenerateRequest) -> PdfReportResult:
        output_path = self._build_output_path(payload.platform)
        platform = payload.platform.lower().strip()

        if platform in ("vk", "ok", "telegram"):
            query = (select(PublicSocialLink.id)
                     .join(Public, Public.id == PublicSocialLink.public_id)
                     .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
                     .where(Public.organization_id == user.organization_id, SocialNetwork.code == platform))
            requested = parse_public_social_link_ids(payload.public_social_link_id)
            if requested:
                query = query.where(PublicSocialLink.id.in_(requested))
            ids = (await self._db.execute(query)).scalars().all()
            payload = payload.model_copy(update={"public_social_link_id": ",".join(map(str, ids)) or "00000000-0000-0000-0000-000000000000"})
            pdf_path = await self._generate_vk(user, payload, output_path)
        else:
            pdf_path = self._orchestrator.generate_report(
                platform=payload.platform,
                csv_path=payload.csv_path,
                output_path=output_path,
            )
        return PdfReportResult(path=pdf_path)

    async def _generate_vk(
        self,
        user: User,
        payload: ReportGenerateRequest,
        output_path: str,
    ) -> str:
        if not user.organization_id:
            raise ReportError("У пользователя не назначена организация")
        municipality_name = self._municipality_filter(payload.municipality_name)

        # Отчёт по VK всегда один — про обращения жителей. Без выбранного
        # округа он собирается по всем сразу.
        return await self._generate_municipality_pains_pdf(
            user,
            payload,
            output_path,
            municipality_name=municipality_name,
        )

    async def _generate_municipality_pains_pdf(
        self,
        user: User,
        payload: ReportGenerateRequest,
        output_path: str,
        *,
        municipality_name: str | None,
    ) -> str:
        t0 = time.monotonic()
        try:
            summary = await self._summary.get_summary(
                user,
                period=payload.period,
                public_social_link_id=payload.public_social_link_id,
                municipality_name=municipality_name,
            )
            pains = await self._pain_list.list_pains(
                user,
                period=payload.period,
                public_social_link_id=payload.public_social_link_id,
                municipality_name=municipality_name,
            )
            # Та же сводка без фильтра территории: без неё цифры округа не с чем
            # сравнить — 31% ответов это провал или обычное дело, непонятно.
            krai_summary = await self._summary.get_summary(
                user,
                period=payload.period,
                public_social_link_id=payload.public_social_link_id,
            ) if municipality_name else None
            burning = await self._burning_cases(
                user,
                period=payload.period,
                public_social_link_id=payload.public_social_link_id,
                municipality_name=municipality_name,
            )
            previous = await self._previous_period(
                user,
                period=payload.period,
                public_social_link_id=payload.public_social_link_id,
                municipality_name=municipality_name,
            )
        except ValueError as exc:
            raise ReportError(str(exc)) from exc

        source_label = "выбранные площадки" if payload.public_social_link_id else "все площадки"
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(
            _REPORT_POOL,
            functools.partial(
                generate_municipality_pains_pdf,
                municipality_name=municipality_name,
                period=payload.period,
                summary=summary,
                pains=pains,
                output_path=output_path,
                source_label=source_label,
                krai_summary=krai_summary,
                burning_cases=burning,
                previous=previous,
            ),
        )
        logger.info(
            "Municipality pains PDF timings: pains=%d total=%.1fs",
            len(pains),
            time.monotonic() - t0,
        )
        return path

    async def _previous_period(
        self,
        user: User,
        *,
        period: str,
        public_social_link_id: str | None,
        municipality_name: str | None,
    ) -> dict | None:
        """Обращения и категории за предыдущее такое же окно.

        Нужно, чтобы сказать «стало больше или меньше». За всё время сравнивать
        не с чем, поэтому там возвращается ``None``.
        """

        since = period_to_since(period)
        if since is None:
            return None
        length = datetime.now(timezone.utc) - since
        window = {"since": since - length, "until": since}
        kwargs = {
            "link_id": _link_filter(public_social_link_id),
            "municipality_name": municipality_name,
        }
        appeals = await self._signals.count_appeals(user, **window, **kwargs)
        rows = await self._signals.category_rows(user, **window, **kwargs)
        return {
            "appeals": int(appeals or 0),
            "categories": {
                str(row.category or "").strip().lower(): int(row.cnt or 0) for row in rows
            },
        }

    async def _burning_cases(
        self,
        user: User,
        *,
        period: str,
        public_social_link_id: str | None,
        municipality_name: str | None,
        limit: int = 5,
    ) -> list[dict]:
        """Адреса с самым плотным негативом, по которым власть не отвечала.

        Именно они интересны главе: топ по объёму он и так знает, а это точки,
        где людям не ответили.
        """

        rows = await self._comments.list_burning_cases(
            user,
            since=period_to_since(period),
            link_id=_link_filter(public_social_link_id),
            municipality_name=municipality_name,
        )
        # Склейка и подписи — те же, что в карточках болей: по каноническому
        # имени места от геокодера. Иначе одна улица распадается на несколько
        # строк, потому что модель пишет адрес каждый раз по-своему.
        keys = PainSliceService(self._db).case_keys(rows).get("", {})

        merged: dict[str, dict] = {}
        for row in rows:
            title = str(row.case_name or "").strip()
            # Порог в два негативных обращения оставлял блок пустым: на живых
            # данных у большинства адресов их один. Берём все без ответа и
            # сортируем — наверх всё равно попадут самые плотные.
            if int(row.answered_count or 0) > 0 or int(row.negative_count or 0) < 1:
                continue
            entry = keys.get((
                title,
                str(row.public_region or ""),
                str(row.public_name or ""),
                str(row.source_title or ""),
            ))
            # Ключа нет — это либо не адрес, а название территории, либо место
            # без координат. Главе такие строки ничего не говорят.
            if entry is None:
                continue
            key, display = entry
            item = merged.get(key)
            if item is None:
                merged[key] = {"title": display, "raw_title": title, "negative": 0, "mentions": 0}
                item = merged[key]
            elif len(title) < len(item["raw_title"]):
                item["title"] = display
                item["raw_title"] = title
            item["negative"] += int(row.negative_count or 0)
            item["mentions"] += int(row.mentions_count or 0)
        ordered = sorted(merged.values(), key=lambda item: item["negative"], reverse=True)
        return ordered[:limit]

    @staticmethod
    def _municipality_filter(value: str | None) -> str | None:
        try:
            return ",".join(canonicalize_municipality_filters(value)) or None
        except ValueError as exc:
            raise ReportError(str(exc)) from exc

    def _build_output_path(self, platform: str) -> str:
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_platform = platform.lower().strip() or "report"
        filename = f"report_{safe_platform}_{stamp}_{uuid4().hex[:8]}.pdf"
        return str((self._reports_dir / filename).resolve())
