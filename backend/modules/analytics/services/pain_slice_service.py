"""Общие расчёты срезов болей по периоду и площадке."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.analytics.repositories.comment_repository import CommentRepository
from backend.modules.analytics.services.pain_map_service import PainMapService, parse_address_hierarchy
from backend.modules.analytics.utils.case_extractor import case_location_key, is_valid_case_title
from backend.modules.analytics.utils.case_merge import CaseKeys, label_rank, title_parts
from backend.modules.analytics.utils.location_geocode_strategy import LocationContext
from backend.modules.analytics.utils.public_link_filter import PublicSocialLinkFilter
from backend.modules.analytics.utils.severity_rules import severity_from_share


class PainSliceService:
    """Считает mentions/publications/comment_ids для pain'ов в фильтре."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        comment_repository: CommentRepository | None = None,
    ) -> None:
        self._db = db
        self._comment_repository = comment_repository or CommentRepository(db)

    async def count_mentions(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since=None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> dict[str, int]:
        """Возвращает количество уникальных комментариев по каждой боли."""

        kwargs = {"since": since, "link_id": link_id}
        if municipality_name is not None:
            kwargs["municipality_name"] = municipality_name
        return await self._comment_repository.count_mentions_by_pain(pain_ids, **kwargs)

    async def count_publications(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since=None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> dict[str, int]:
        """Возвращает количество публикаций с комментариями по каждой боли."""

        kwargs = {"since": since, "link_id": link_id}
        if municipality_name is not None:
            kwargs["municipality_name"] = municipality_name
        return await self._comment_repository.count_publications_by_pain(pain_ids, **kwargs)

    async def collect_comment_ids(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since=None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> dict[str, set[str]]:
        """Возвращает видимые comment_id по каждой боли."""

        kwargs = {"since": since, "link_id": link_id}
        if municipality_name is not None:
            kwargs["municipality_name"] = municipality_name
        return await self._comment_repository.collect_comment_ids_by_pain(pain_ids, **kwargs)

    async def collect_comment_examples(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since=None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
        limit_per_pain: int = 3,
    ) -> dict[str, list[dict]]:
        """Возвращает живые цитаты по каждой боли внутри фильтра."""

        kwargs = {"since": since, "link_id": link_id, "limit_per_pain": limit_per_pain}
        if municipality_name is not None:
            kwargs["municipality_name"] = municipality_name
        return await self._comment_repository.list_comment_examples_by_pain(pain_ids, **kwargs)

    async def count_publications_for_pain(
        self,
        pain_id: uuid.UUID,
        *,
        since=None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> int:
        """Считает публикации одной боли в фильтре."""

        result = await self.count_publications(
            [pain_id],
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        return result.get(str(pain_id), 0)

    async def _case_rows(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None,
    ):
        """Живые адресные кейсы по болям вместе с контекстом паблика."""

        kwargs = {"since": since, "link_id": link_id}
        if municipality_name is not None:
            kwargs["municipality_name"] = municipality_name
        return await self._comment_repository.list_case_counts_by_pain(pain_ids, **kwargs)

    def case_keys(self, rows) -> dict[str, dict[tuple, tuple[str, str]]]:
        """Ключ склейки и подпись для каждого написания адреса.

        Возвращает ``{pain_id: {написание с контекстом: (ключ, подпись)}}``.
        У строк без боли группа пустая — по ней их и забирают.
        Контекст паблика входит в ключ: одноимённые улицы в разных сёлах —
        разные улицы, и складывать их нельзя.
        """

        map_service = PainMapService(self._db)
        geo_cache = map_service.cache_snapshot()
        # Один адрес встречается у нескольких болей, а поиск координат каждый
        # раз заново разбирает название. Считаем раз на уникальный адрес.
        geo_by_context: dict[tuple[str, str, str, str], dict | None] = {}
        mergers: dict[str, CaseKeys] = {}
        keys: dict[str, dict[tuple, tuple[str, str]]] = {}
        labels: dict[tuple, str] = {}
        label_of: dict[tuple, tuple] = {}

        for row in rows:
            # Горящие адреса отчёта приходят без боли: там строки собраны по
            # адресам, а не по темам. Такие складываем в одну общую группу.
            pain_id = str(getattr(row, "pain_id", "") or "")
            title = str(row.case_name or "").strip()
            if not title or not is_valid_case_title(title):
                continue
            memo_key = (
                title,
                str(row.public_region or ""),
                str(row.public_name or ""),
                str(row.source_title or ""),
            )
            if memo_key in geo_by_context:
                geo = geo_by_context[memo_key]
            else:
                # Горящие адреса отчёта берутся другим запросом: образца
                # комментария и разобранного адреса в этих строках нет.
                context = LocationContext(
                    case_name=title,
                    public_region=memo_key[1],
                    public_name=memo_key[2],
                    source_title=memo_key[3],
                    comment_text=str(getattr(row, "sample_comment", "") or ""),
                    address=str(getattr(row, "sample_address", "") or ""),
                    address_hierarchy=parse_address_hierarchy(
                        getattr(row, "sample_address_hierarchy", None)
                    ),
                )
                geo = map_service.cached_geocode_for_context(context, geo_cache)
                geo_by_context[memo_key] = geo

            resolved = mergers.setdefault(pain_id, CaseKeys()).add(title, geo)
            if resolved is None:
                continue
            keys.setdefault(pain_id, {})[memo_key] = resolved

            # Подпись места выбираем на все темы сразу. Иначе одна улица
            # называлась в «Дорогах» так, как её чаще писали там, а в «ЖКХ» —
            # иначе, и выглядело это как две разные строки.
            lat, lon = geo.get("lat"), geo.get("lon")
            cell = (round(float(lat), 1), round(float(lon), 1)) if lat is not None and lon is not None else None
            label_key = (*title_parts(resolved[1]), cell)
            place_stems = frozenset(
                case_location_key(
                    " ".join(
                        part
                        for part in (
                            str(geo.get("locality") or ""),
                            str(geo.get("municipality") or ""),
                        )
                        if part
                    )
                ).split()
            )
            best = labels.get(label_key)
            if best is None or label_rank(resolved[1], place_stems) < label_rank(best, place_stems):
                labels[label_key] = resolved[1]
            label_of[(pain_id, memo_key)] = label_key

        for pain_id, merger in mergers.items():
            remap = merger.remap()
            if not remap:
                continue
            for memo_key, (key, display) in list(keys.get(pain_id, {}).items()):
                if key in remap:
                    keys[pain_id][memo_key] = (remap[key], display)

        for pain_id, entries in keys.items():
            for memo_key, (key, display) in entries.items():
                entries[memo_key] = (key, labels.get(label_of.get((pain_id, memo_key)), display))
        return keys

    async def case_merge_map(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since=None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> dict[str, dict[str, tuple[str, str]]]:
        """Ключи склейки по одному написанию — для списков из снапшота.

        В снапшоте у адреса есть только название, без паблика. Если одно и то
        же написание встретилось в разных местах края, склеивать его нельзя:
        такое написание отдаётся неразделяемым.
        """

        rows = await self._case_rows(
            pain_ids,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        by_context = self.case_keys(rows)

        flat: dict[str, dict[str, tuple[str, str]]] = {}
        for pain_id, entries in by_context.items():
            variants: dict[str, set[str]] = {}
            chosen: dict[str, tuple[str, str]] = {}
            for memo_key, value in entries.items():
                title = memo_key[0]
                variants.setdefault(title, set()).add(value[0])
                chosen[title] = value
            flat[pain_id] = {
                title: value
                for title, value in chosen.items()
                if len(variants[title]) == 1
            }
        return flat

    async def collect_top_cases(
        self,
        pain_ids: list[uuid.UUID],
        *,
        since=None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
        limit_per_pain: int | None = 5,
    ) -> dict[str, dict]:
        """Возвращает компактную live-сводку адресов для карточек болей.

        Формат результата: ``{pain_id: {"top_cases": [...], "cases_count": N}}``.
        ``cases_count`` считает все валидные дедуплицированные адреса, а
        ``top_cases`` ограничен, чтобы карточка не превращалась в простыню.
        """

        rows = await self._case_rows(
            pain_ids,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        keys = self.case_keys(rows)

        merged: dict[str, dict[str, dict]] = {}
        for row in rows:
            pain_id = str(row.pain_id)
            title = str(row.case_name or "").strip()
            memo_key = (
                title,
                str(row.public_region or ""),
                str(row.public_name or ""),
                str(row.source_title or ""),
            )
            entry = keys.get(pain_id, {}).get(memo_key)
            if entry is None:
                continue
            key, display = entry
            cases = merged.setdefault(pain_id, {})
            mentions = int(row.mentions_count or 0)
            if key in cases:
                cases[key]["mentions_count"] += mentions
                # Из нескольких написаний оставляем самое короткое — обычно
                # это чистый адрес без пояснений вроде «у складов Янта».
                if len(title) < len(cases[key]["raw_title"]):
                    cases[key]["title"] = display
                    cases[key]["raw_title"] = title
            else:
                cases[key] = {
                    "title": display,
                    "raw_title": title,
                    "mentions_count": mentions,
                }

        result: dict[str, dict] = {}
        for pain_id, cases in merged.items():
            ordered = sorted(
                cases.values(),
                key=lambda item: item["mentions_count"],
                reverse=True,
            )
            result[pain_id] = {
                "top_cases": ordered if limit_per_pain is None else ordered[:limit_per_pain],
                "cases_count": len(ordered),
            }
        return result

    @staticmethod
    def severity_from_share(mentions: int, total: int) -> str:
        """Severity среза — через канон severity_rules.severity_from_share."""
        return severity_from_share(mentions, total)
