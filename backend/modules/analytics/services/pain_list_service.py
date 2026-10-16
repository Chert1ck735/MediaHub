"""Сервис списка болей analytics."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User
from backend.modules.analytics.repositories.pain_repository import PainRepository
from backend.modules.analytics.repositories.snapshot_repository import SnapshotRepository
from backend.modules.analytics.schemas import PainListItemResponse, PainSubproblemRef
from backend.modules.analytics.services.pain_context_service import PainContextService
from backend.modules.analytics.services.pain_slice_service import PainSliceService
from backend.modules.analytics.services.payload_helpers import clean_strategy_text
from backend.modules.analytics.utils.interfaces import PainRepositoryProtocol, SnapshotRepositoryProtocol
from backend.modules.analytics.utils.time_helpers import period_to_since
from backend.modules.analytics.utils.public_link_filter import (
    compact_public_social_link_filter,
    parse_public_social_link_ids,
)


class PainListService:
    """Формирует список болей без SQL и бизнес-логики в router."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        snapshot_repository: SnapshotRepositoryProtocol | None = None,
        pain_repository: PainRepositoryProtocol | None = None,
    ):
        self._snapshot_repository = snapshot_repository or SnapshotRepository(db)
        self._pain_repository = pain_repository or PainRepository(db)
        self._slice_service = PainSliceService(db)
        self._context_service = PainContextService()

    async def list_pains(
        self,
        user: User,
        *,
        period: str = "all",
        public_social_link_id: str | None = None,
        municipality_name: str | None = None,
    ) -> list[PainListItemResponse]:
        """Возвращает pain cards с учётом периода и площадки."""

        # тот же снапшот, что у карточки боли и /summary
        snapshot = await self._snapshot_repository.get_latest_vk(user)
        if snapshot is None:
            return []

        link_ids = parse_public_social_link_ids(public_social_link_id)
        link_filter = compact_public_social_link_filter(link_ids)
        since = period_to_since(period)
        pains = await self._snapshot_repository.list_pains(str(snapshot.id))
        needs_recount = since is not None or link_filter is not None or municipality_name is not None
        pain_ids = [pain.id for pain in pains]

        # счётчики всегда живые: снапшотные протухают между пересборками
        mentions = await self._slice_service.count_mentions(
            pain_ids,
            since=since,
            link_id=link_filter,
            municipality_name=municipality_name,
        )
        publications = await self._slice_service.count_publications(
            pain_ids,
            since=since,
            link_id=link_filter,
            municipality_name=municipality_name,
        )
        valid_cids = await self._slice_service.collect_comment_ids(
            pain_ids,
            since=since,
            link_id=link_filter,
            municipality_name=municipality_name,
        ) if needs_recount else {}
        live_examples = await self._slice_service.collect_comment_examples(
            pain_ids,
            since=since,
            link_id=link_filter,
            municipality_name=municipality_name,
        ) if needs_recount else {}
        # полный список: карточка показывает топ-4, остальные — по «+ ещё»
        live_cases = await self._slice_service.collect_top_cases(
            pain_ids,
            since=since,
            link_id=link_filter,
            municipality_name=municipality_name,
            limit_per_pain=100,
        )

        contexts: list[tuple] = []
        for pain in pains:
            effective_mentions = mentions.get(str(pain.id), 0)
            if needs_recount and effective_mentions == 0:
                continue
            context = self._context_service.build(snapshot, pain)
            # Снапшот хранит подпроблемы и примеры за всё время. Если этого не
            # сузить, в недельном отчёте у подпроблемы стояло 2717 упоминаний
            # при 122 обращениях во всей категории, а примеры были из другого
            # периода. Фильтруем при любом фильтре, а не только по площадке.
            if needs_recount:
                context = self._context_service.filter_by_comment_ids(
                    context,
                    valid_cids.get(str(pain.id), set()),
                )
                # Примеры снапшота собраны по всем территориям и за всё время,
                # под узкий фильтр от них обычно не остаётся ничего. Тогда
                # берём комментарии, которые в этот фильтр реально попали.
                if not context.get("comment_examples"):
                    context["comment_examples"] = live_examples.get(str(pain.id), [])
            contexts.append((pain, effective_mentions, context))

        severity_overrides: dict[str, str] = {}
        if needs_recount:
            total_mentions = sum(item[1] for item in contexts)
            for pain, effective_mentions, _ in contexts:
                severity_overrides[str(pain.id)] = self._slice_service.severity_from_share(
                    effective_mentions,
                    total_mentions,
                )

        # Разом на весь список: поштучно это три запроса к базе на карточку.
        shown_ids = [str(pain.id) for pain, _mentions, _context in contexts]
        strategies_by_pain = await self._pain_repository.get_strategies_map(shown_ids)
        evidence_by_pain = await self._pain_repository.get_evidence_urls_map(shown_ids)

        items: list[PainListItemResponse] = []
        for pain, effective_mentions, context in contexts:
            pain_strategies = strategies_by_pain.get(str(pain.id), [])
            strategy_ids = [strategy_id for strategy_id, _description in pain_strategies]
            strategies = [
                clean_strategy_text(description)
                for _strategy_id, description in pain_strategies
                if clean_strategy_text(description)
            ]
            evidence = evidence_by_pain.get(str(pain.id), [])
            case_summary = live_cases.get(str(pain.id), {"top_cases": [], "cases_count": 0})
            top_cases = case_summary["top_cases"]

            items.append(
                PainListItemResponse(
                    id=str(pain.id),
                    title=pain.title,
                    category=pain.category,
                    subcategory=context.get("subcategory"),
                    mentions_count=effective_mentions,
                    publications_count=publications.get(str(pain.id), 0),
                    severity_level=severity_overrides.get(str(pain.id), pain.severity_level.value),
                    status=pain.status.value,
                    comment_examples=list(context.get("comment_examples", []))[:2],
                    subproblems=list(context.get("subproblems", []))[:5],
                    subproblem_items=[
                        PainSubproblemRef(
                            title=str(item.get("title") or ""),
                            mentions_count=int(item.get("mentions_count") or 0),
                        )
                        for item in (context.get("subproblem_items") or [])[:5]
                        if str(item.get("title") or "").strip()
                    ],
                    subproblem_count=len(context.get("subproblem_items", []) or []),
                    top_cases=top_cases,
                    cases_count=case_summary["cases_count"],
                    strategy_id=strategy_ids[0] if strategy_ids else None,
                    communication_strategy=strategies[0] if strategies else None,
                    strategy_preview=strategies[0] if strategies else None,
                    evidence_posts=evidence,
                )
            )
        return items
