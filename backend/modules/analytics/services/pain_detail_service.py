"""Сервис детальной карточки боли."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User
from backend.modules.analytics.repositories.comment_repository import (
    NO_SUBCATEGORY_TITLE,
    CommentRepository,
)
from backend.modules.analytics.repositories.pain_repository import PainRepository
from backend.modules.analytics.repositories.snapshot_repository import SnapshotRepository
from backend.modules.analytics.schemas import PainDetailResponse
from backend.modules.analytics.constants import SUBCATEGORY_ALIASES
from backend.modules.analytics.services.pain_context_service import PainContextService
from backend.modules.analytics.services.pain_lifecycle_service import PainLifecycleService
from backend.modules.analytics.services.pain_map_service import PainMapService, parse_address_hierarchy
from backend.modules.analytics.services.pain_slice_service import PainSliceService
from backend.modules.analytics.services.payload_helpers import clean_strategy_text
from backend.modules.analytics.utils.case_merge import CaseKeys
from backend.modules.analytics.utils.case_extractor import is_valid_case_title
from backend.modules.analytics.utils.comment_examples import vk_comment_url
from backend.modules.analytics.utils.interfaces import PainRepositoryProtocol, SnapshotRepositoryProtocol
from backend.modules.analytics.utils.location_geocode_strategy import LocationContext
from backend.modules.analytics.utils.public_link_filter import (
    PublicSocialLinkFilter,
    compact_public_social_link_filter,
    parse_public_social_link_ids,
)
from backend.modules.analytics.utils.text_normalize import trim_text
from backend.modules.analytics.utils.time_helpers import period_to_since


class PainDetailService:
    """Готовит детальный ответ по боли без бизнес-логики в router."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        pain_repository: PainRepositoryProtocol | None = None,
        snapshot_repository: SnapshotRepositoryProtocol | None = None,
        comment_repository: CommentRepository | None = None,
    ) -> None:
        """Создаёт сервис детальной карточки боли через интерфейсы."""
        self._db = db
        self._pain_repository = pain_repository or PainRepository(db)
        self._snapshot_repository = snapshot_repository or SnapshotRepository(db)
        self._comment_repository = comment_repository or CommentRepository(db)
        self._slice_service = PainSliceService(db)
        self._context_service = PainContextService()
        self._lifecycle_service = PainLifecycleService(db)

    async def get_detail(
        self,
        user: User,
        pain_id: str,
        *,
        public_social_link_id: str | None = None,
        period: str = "all",
        municipality_name: str | None = None,
    ) -> PainDetailResponse:
        """Возвращает детальную карточку боли (с учётом площадки и периода)."""

        pain = await self._pain_repository.get_by_id(pain_id, user)
        if pain is None:
            raise ValueError("Боль не найдена")

        link_ids = parse_public_social_link_ids(public_social_link_id)
        link_filter = compact_public_social_link_filter(link_ids)
        since = period_to_since(period)
        raw_strategies = await self._pain_repository.get_strategy_descriptions(str(pain.id))
        strategies = [clean_strategy_text(item) for item in raw_strategies if clean_strategy_text(item)]
        strategy_ids = await self._pain_repository.get_strategy_ids(str(pain.id))
        evidence = await self._pain_repository.get_evidence_urls(str(pain.id))
        example_kwargs = {"link_id": link_filter}
        if municipality_name is not None:
            example_kwargs["municipality_name"] = municipality_name
        comment_examples = await self._pain_repository.get_comment_examples(
            str(pain.id),
            **example_kwargs,
        )
        snapshot = await self._snapshot_repository.get_latest_vk(user)
        context = self._context_service.build(snapshot, pain)
        # Адреса внутри подпроблем лежат в снапшоте отдельными написаниями:
        # «ул. Дубовицкого» и «Дубовицкого, посёлок Солонцы» — одна улица, а
        # показывались двумя строками. Ключи склейки берём из живой выборки,
        # где у адреса есть контекст паблика.
        context = self._context_service.merge_cases(
            context,
            (await self._slice_service.case_merge_map(
                [pain.id],
                since=since,
                link_id=link_filter,
                municipality_name=municipality_name,
            )).get(str(pain.id), {}),
        )

        # живой счётчик: снапшотный pain.mentions_count протухает между пересборками
        mentions = (await self._slice_service.count_mentions(
            [pain.id],
            municipality_name=municipality_name,
        )).get(str(pain.id), 0)
        publications = int(context.get("publications_count", 0) or 0)
        description = pain.description
        sentiment_counts = context.get("sentiment_counts", {})
        message_type_counts = context.get("message_type_counts", {})
        request_count = int(context.get("request_count", 0) or 0)
        complaint_count = int(context.get("complaint_count", 0) or 0)
        severity = pain.severity_level.value

        if link_filter is not None or since is not None or municipality_name is not None:
            # Фильтр по площадке/периоду: все счётчики считаем из живых комментов,
            # иначе шапка (снапшот, всё время) расходится со списком слева.
            mentions = (await self._slice_service.count_mentions(
                [pain.id],
                since=since,
                link_id=link_filter,
                municipality_name=municipality_name,
            )).get(str(pain.id), 0)
            publications = await self._slice_service.count_publications_for_pain(
                pain.id,
                since=since,
                link_id=link_filter,
                municipality_name=municipality_name,
            )
            if link_filter is not None or municipality_name is not None:
                valid_cids = (await self._slice_service.collect_comment_ids(
                    [pain.id],
                    since=since,
                    link_id=link_filter,
                    municipality_name=municipality_name,
                )).get(str(pain.id), set())
                context = self._context_service.filter_by_comment_ids(context, valid_cids)
            # Без описания-повтора: счётчики упоминаний/публикаций уже в шапке боли.
            description = ""
            signal_counts = await self._get_signal_counts_for_pain(
                pain.id,
                link_filter,
                since,
                municipality_name=municipality_name,
            )
            sentiment_counts = signal_counts["sentiment_counts"]
            message_type_counts = signal_counts["message_type_counts"]
            request_count = message_type_counts["request"]
            complaint_count = message_type_counts["complaint"] + message_type_counts["sarcasm"]
            if (
                link_filter is not None
                and municipality_name is None
                and not comment_examples
                and not context.get("comment_examples")
            ):
                comment_examples = await self._fallback_comment_examples(pain.id, link_filter)
            severity = await self._compute_filtered_severity(
                pain.id,
                snapshot,
                link_filter,
                since,
                municipality_name=municipality_name,
            )

        cleaned_subitems = self._context_service.clean_subproblem_items(snapshot, context)
        # Число в чипе подпроблемы = число реальных комментов (тот же источник, что список),
        # иначе снапшотный счётчик расходится с тем, что видно при клике.
        subcount_kwargs = {"pain_id": pain.id, "link_id": link_filter, "since": since}
        if municipality_name is not None:
            subcount_kwargs["municipality_name"] = municipality_name
        live_subcounts = await self._comment_repository.count_pain_comment_subcategories(
            **subcount_kwargs,
        )
        for item in cleaned_subitems:
            # Нет ключа в live_subcounts = живых комментов по этой подпроблеме
            # нет вовсе, поэтому 0, а не «оставить снапшотное число». Иначе чип
            # показывал ненулевой счётчик, а клик по нему давал пустой список.
            item["mentions_count"] = live_subcounts.get(str(item.get("title", "")).lower(), 0)
        cleaned_subitems = [it for it in cleaned_subitems if int(it.get("mentions_count", 0) or 0) > 0]
        # Подкатегории, появившиеся после пересборки снапшота, — тоже чипами,
        # но только из таксономии категории этой боли: сырые comment_analysis
        # могут нести чужую или свободную подкатегорию, чип из неё — мусор.
        allowed_subs = SUBCATEGORY_ALIASES.get(str(pain.title or ""))
        # Тот же фильтр — и для чипов из снапшота: пока снапшот не пересобран,
        # в нём могут лежать подкатегории из старой разметки.
        if allowed_subs is not None:
            cleaned_subitems = [
                it for it in cleaned_subitems
                if str(it.get("title", "")).lower() in allowed_subs
            ]
        known_titles = {str(it.get("title", "")).lower() for it in cleaned_subitems}
        for sub, cnt in live_subcounts.items():
            if not sub or sub in known_titles or int(cnt or 0) <= 0:
                continue
            if allowed_subs is not None and sub not in allowed_subs:
                continue
            cleaned_subitems.append({"title": sub, "mentions_count": int(cnt)})
        live_cases = await self._live_cases_by_subcategory(
            pain.id,
            link_filter,
            since,
            municipality_name=municipality_name,
        )
        case_summary = (
            await self._slice_service.collect_top_cases(
                [pain.id],
                since=since,
                link_id=link_filter,
                municipality_name=municipality_name,
                limit_per_pain=None,
            )
        ).get(str(pain.id), {"top_cases": [], "cases_count": 0})
        for item in cleaned_subitems:
            sub_key = str(item.get("title", "")).lower()
            item["cases"] = live_cases.get(sub_key, [])
        cleaned_subitems.sort(key=lambda it: int(it.get("mentions_count", 0) or 0), reverse=True)
        # комменты без подкатегории — отдельным чипом в конце, с их адресами
        no_subcat = int(live_subcounts.get("", 0) or 0)
        if no_subcat > 0:
            cleaned_subitems.append({
                "title": NO_SUBCATEGORY_TITLE,
                "mentions_count": no_subcat,
                "cases": live_cases.get("", []),
            })
        reaction_gap = await self._lifecycle_service.compute_reaction_gap(pain.id)
        communication_strategy = strategies[0] if strategies else context.get("communication_strategy")

        return PainDetailResponse(
            id=str(pain.id),
            title=pain.title,
            description=description,
            category=pain.category,
            subcategory=context.get("subcategory"),
            mentions_count=mentions,
            publications_count=publications,
            severity_level=severity,
            status=pain.status.value,
            comment_examples=comment_examples or list(context.get("comment_examples", [])),
            subproblems=list(context.get("subproblems", [])),
            subproblem_items=cleaned_subitems,
            top_cases=case_summary["top_cases"],
            cases_count=case_summary["cases_count"],
            sentiment_counts=sentiment_counts,
            message_type_counts=message_type_counts,
            request_count=request_count,
            complaint_count=complaint_count,
            communication_strategy=communication_strategy,
            strategy_ids=strategy_ids,
            strategies=strategies or ([communication_strategy] if communication_strategy else []),
            evidence_posts=evidence,
            reaction_gap=reaction_gap,
        )

    async def _get_signal_counts_for_pain(
        self,
        pain_id: uuid.UUID,
        link_id: PublicSocialLinkFilter = None,
        since=None,
        municipality_name: str | None = None,
    ) -> dict:
        """Считает sentiment/message_type одной боли (опц. площадка/период)."""

        kwargs = {"since": since}
        if municipality_name is not None:
            kwargs["municipality_name"] = municipality_name
        rows = await self._comment_repository.signal_counts_rows_for_pain(
            pain_id,
            link_id,
            **kwargs,
        )
        sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}
        message_type_counts = {"complaint": 0, "request": 0, "gratitude": 0, "offtopic": 0, "sarcasm": 0}
        for sentiment, message_type, count in rows:
            if sentiment and sentiment.value in sentiment_counts:
                sentiment_counts[sentiment.value] += int(count or 0)
            key = str(message_type or "").strip()
            if key in message_type_counts:
                message_type_counts[key] += int(count or 0)
        return {"sentiment_counts": sentiment_counts, "message_type_counts": message_type_counts}

    async def _live_cases_by_subcategory(
        self,
        pain_id: uuid.UUID,
        link_id: PublicSocialLinkFilter = None,
        since=None,
        municipality_name: str | None = None,
    ) -> dict[str, list[dict]]:
        """Адресные кейсы карточки из текущего comment_analysis, а не из снапшота."""

        kwargs = {"link_id": link_id, "since": since}
        if municipality_name is not None:
            kwargs["municipality_name"] = municipality_name
        rows = await self._comment_repository.list_case_rows_for_pain(pain_id, **kwargs)
        grouped: dict[str, dict[str, dict]] = {}
        seen_mentions: dict[tuple[str, str], set[str]] = {}
        case_keys = CaseKeys()
        map_service = PainMapService(self._db)
        geo_cache = map_service.cache_snapshot()
        for row in rows:
            title = str(row.case_name or "").strip()
            if not title or not is_valid_case_title(title):
                continue
            # пустая подкатегория — группа "" (чип «Без подкатегории»)
            sub_key = str(row.subcategory or "").strip().lower()
            context = LocationContext(
                case_name=title,
                public_region=str(row.public_region or ""),
                public_name=str(row.public_name or ""),
                source_title=str(row.source_title or ""),
                comment_text=str(row.text or ""),
                address=str(row.address or ""),
                address_hierarchy=parse_address_hierarchy(row.address_hierarchy),
            )
            geo = map_service.cached_geocode_for_context(context, geo_cache)
            if not geo:
                continue
            # Ключ и подпись — по общим правилам: иначе один адрес показывался
            # тут несколькими строками, а рядом лежали названия территорий.
            resolved = case_keys.add(title, geo)
            if resolved is None:
                continue
            case_key, display = resolved
            cases = grouped.setdefault(sub_key, {})
            case = cases.setdefault(
                case_key,
                {
                    "title": display,
                    "raw_title": title,
                    "mentions_count": 0,
                    "comment_examples": [],
                    "sentiment_counts": {"positive": 0, "neutral": 0, "negative": 0},
                    "message_type_counts": {
                        "complaint": 0,
                        "request": 0,
                        "gratitude": 0,
                        "offtopic": 0,
                        "sarcasm": 0,
                    },
                    "request_count": 0,
                    "complaint_count": 0,
                    "source_urls": [],
                },
            )

            mention_key = f"{row.publication_id}:{row.external_id or row.comment_id}"
            mention_seen = seen_mentions.setdefault((sub_key, case_key), set())
            if mention_key in mention_seen:
                continue
            mention_seen.add(mention_key)
            case["mentions_count"] += 1

            sentiment = row.sentiment.value if row.sentiment else None
            if sentiment in case["sentiment_counts"]:
                case["sentiment_counts"][sentiment] += 1

            message_type = str(row.message_type or "")
            if message_type in case["message_type_counts"]:
                case["message_type_counts"][message_type] += 1
            if message_type == "request":
                case["request_count"] += 1
            if message_type in {"complaint", "sarcasm"}:
                case["complaint_count"] += 1

            url = vk_comment_url(row.publication_url, row.external_id) or row.publication_url
            if url and url not in case["source_urls"]:
                case["source_urls"].append(url)
            if len(case["comment_examples"]) < 5:
                text = trim_text(str(row.text or ""), 320)
                if text:
                    case["comment_examples"].append(
                        {
                            "text": text,
                            "url": url,
                            "publication_url": row.publication_url,
                            "comment_id": str(row.comment_id) if row.comment_id else None,
                            "message_type": message_type or None,
                            "sentiment": sentiment,
                        }
                    )

        # «ул. Нагорная» и «Нагорная, посёлок Солонцы» встретились под разными
        # ключами — сводим их и складываем накопленное.
        remap = case_keys.remap()
        if remap:
            for sub_key, cases in grouped.items():
                for source, target in remap.items():
                    if source not in cases or target not in cases:
                        continue
                    moved = cases.pop(source)
                    kept = cases[target]
                    kept["mentions_count"] += moved["mentions_count"]
                    seen = {
                        example.get("comment_id")
                        for example in kept["comment_examples"]
                    }
                    for example in moved["comment_examples"]:
                        if len(kept["comment_examples"]) >= 5:
                            break
                        if example.get("comment_id") not in seen:
                            kept["comment_examples"].append(example)
                    for field in ("request_count", "complaint_count"):
                        kept[field] += moved[field]
                    for counts in ("sentiment_counts", "message_type_counts"):
                        for name, value in moved[counts].items():
                            kept[counts][name] = kept[counts].get(name, 0) + value
                    for url in moved["source_urls"]:
                        if url not in kept["source_urls"]:
                            kept["source_urls"].append(url)

        return {
            sub_key: sorted(
                cases.values(),
                key=lambda item: item["mentions_count"],
                reverse=True,
            )
            for sub_key, cases in grouped.items()
        }

    async def _fallback_comment_examples(
        self,
        pain_id: uuid.UUID,
        link_id: PublicSocialLinkFilter,
    ) -> list[dict]:
        """Берёт свежие примеры напрямую из CommentPain, если snapshot не дал примеров."""

        rows = await self._comment_repository.recent_comments_for_pain(pain_id, link_id, limit=5)
        result: list[dict] = []
        for row in rows:
            text = trim_text(str(row.text or ""), 320)
            if not text:
                continue
            result.append(
                {
                    "text": text,
                    "url": vk_comment_url(row.publication_url, row.external_id) or row.publication_url,
                    "publication_url": row.publication_url,
                    "comment_id": str(row.id) if row.id else None,
                    "message_type": row.message_type,
                    "sentiment": row.sentiment.value if row.sentiment else None,
                }
            )
        return result

    async def _compute_filtered_severity(
        self,
        pain_id: uuid.UUID,
        snapshot,
        link_id: PublicSocialLinkFilter = None,
        since=None,
        municipality_name: str | None = None,
    ) -> str:
        """Пересчитывает severity одной боли относительно среза (площадка/период)."""

        if snapshot is None:
            return "low"
        all_pains = await self._snapshot_repository.list_pains(str(snapshot.id))
        mentions = await self._slice_service.count_mentions(
            [pain.id for pain in all_pains],
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        return self._slice_service.severity_from_share(
            mentions.get(str(pain_id), 0),
            sum(mentions.values()),
        )
