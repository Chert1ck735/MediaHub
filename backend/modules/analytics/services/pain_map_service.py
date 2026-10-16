"""Точки для «Карты болей»: адресные кейсы → координаты (кэш) → агрегат.

Геокод через Яндекс/DaData (``utils.geocode``) с файловым кэшем, чтобы не
дёргать геокодер на каждый запрос. Точки агрегируются по координате
(суммарные упоминания), скоуп — организация/период/площадка.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from backend.app.config import settings
from backend.db import Comment, CommentAnalysis, Public, Publication, PublicSocialLink
from backend.db.users import User
from backend.modules.analytics.constants import VK_THEME_META
from backend.modules.analytics.utils.case_extractor import is_valid_case_title
from backend.modules.analytics.utils.address_normalizer import (
    address_canonical_title,
    address_display_title,
)
from backend.modules.analytics.utils.geo_keys import has_capacity, set_runtime_keys
from backend.modules.analytics.utils.geocode import (
    GeoPoint,
    agreement,
    geocode,
    geocode_candidates,
)
from backend.modules.analytics.utils.location_geocode_strategy import (
    LocationContext,
    accept_geocode_result,
    point_in_expected_region,
    build_geocode_queries,
    point_contradicts_public_city,
    resolve_case_locality,
)
from backend.modules.analytics.utils.object_directory import find_object
from backend.modules.analytics.utils.comment_examples import vk_comment_url
from backend.modules.analytics.utils.public_link_filter import (
    PublicSocialLinkFilter,
    normalize_public_social_link_ids,
)
from backend.modules.analytics.utils.municipality_filter import (
    raw_address_municipality_clause,
    raw_comment_municipality_clause,
    raw_municipality_params,
)

_SKIP = {"красноярский край", "улица не указана", "не указана", "разное"}
OTHER_PROBLEM_TYPE = "__other_category__"

# Разобранный geo-кэш и отпечаток файла — см. ``cache_snapshot``.
_CACHE_SNAPSHOT: dict | None = None
_CACHE_SNAPSHOT_KEY: tuple | None = None
STANDARD_PROBLEM_CATEGORIES = tuple(
    sorted({meta["category"].lower() for meta in VK_THEME_META.values()})
)


def _resolve_point(query: str, timeout: int):
    """Точка и список согласных с ней провайдеров.

    Одиночный ответ верен в ~34% случаев, подтверждённый вторым провайдером —
    в ~82% (разметка 530 мест). Пока GEO_REQUIRE_CONSENSUS выключен, точка
    принимается как прежде, но уровень доверия записывается.
    """
    if not settings.GEO_USE_CONSENSUS:
        point = geocode(query, timeout=timeout)
        return point, ([point.source] if point else [])

    candidates = geocode_candidates(query, timeout=timeout)
    point, agreed = agreement(candidates)
    if settings.GEO_REQUIRE_CONSENSUS and len(agreed) < 2:
        return None, agreed
    return point, agreed


def _is_hit(entry) -> bool:
    return isinstance(entry, dict) and "lat" in entry


def _point_from_cache_entry(entry: dict) -> GeoPoint | None:
    """Восстанавливает ответ геокодера из кэша — для повторной отбраковки.

    В записи лежат все поля ответа, поэтому проверять точку заново можно без
    обращения к провайдеру.
    """
    try:
        return GeoPoint(
            lat=float(entry["lat"]),
            lon=float(entry["lon"]),
            region=str(entry.get("region") or ""),
            municipality=str(entry.get("municipality") or ""),
            locality=str(entry.get("locality") or ""),
            district=str(entry.get("district") or ""),
            source=str(entry.get("source") or ""),
            precision=str(entry.get("precision") or ""),
            provider_name=str(entry.get("provider_name") or ""),
            provider_description=str(entry.get("provider_description") or ""),
            provider_kind=str(entry.get("provider_kind") or ""),
            provider_text=str(entry.get("provider_text") or ""),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _object_directory_point(context: LocationContext) -> GeoPoint | None:
    """Объект из справочника Енисей-ГИС вместо обращения к геокодеру.

    Геокодер не знает, где «школа №9» или «остановка на Декабристов», и отдаёт
    улицу или центр округа. Справочник знает и ничего не стоит: ни сети, ни
    квоты. Поиск строгий — без населённого пункта и при нескольких кандидатах
    возвращается пусто.
    """

    locality = resolve_case_locality(context)
    if not locality:
        return None
    hit = find_object(context.case_name, locality)
    if hit is None:
        return None
    return GeoPoint(
        lat=hit.lat,
        lon=hit.lon,
        region=context.public_region or "",
        municipality="",
        locality=hit.locality,
        district="",
        source="enisey_gis",
        precision="exact",
        provider_name=hit.name,
        provider_text=hit.address or hit.name,
        provider_kind=hit.kind,
    )


def _miss_without_answer(entry) -> bool:
    """Отказ, при котором провайдер не ответил вообще.

    Так выглядит и выбранная норма ключей, и сорвавшаяся сеть. Отличается от
    честного отказа, где ответ пришёл, но не подошёл: там в ``source`` лежит имя
    провайдера.
    """
    return (
        isinstance(entry, dict)
        and "_miss" in entry
        and str(entry.get("source") or "none") == "none"
    )


def _miss_fresh(entry, now: float, ttl: float) -> bool:
    if isinstance(entry, dict) and "_miss" in entry:
        return (now - entry["_miss"]) < ttl
    return False


def _json_object(value) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def parse_address_hierarchy(value) -> dict | None:
    """Разбирает значения address_hierarchy, прочитанные из строк SQL."""
    return _json_object(value)


class PainMapService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._cache = settings.geo_cache_path_abs

    def _load(self) -> dict:
        if self._cache.exists():
            try:
                return json.loads(self._cache.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def _save(self, cache: dict) -> None:
        self._cache.parent.mkdir(parents=True, exist_ok=True)
        self._cache.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    async def mark_cases_non_address(self, user: User, cases: list[str]) -> dict:
        """Снимает признак адресного кейса с выбранных названий в организации."""
        if not user.organization_id:
            return {"cases": [], "updated_analyses": 0}

        normalized_cases = sorted({case.strip() for case in cases if case and case.strip()})
        if not normalized_cases:
            return {"cases": [], "updated_analyses": 0}

        stmt = (
            select(CommentAnalysis)
            .join(Comment, Comment.id == CommentAnalysis.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(
                Public.organization_id == user.organization_id,
                func.json_extract_path_text(CommentAnalysis.hierarchy, "case").in_(normalized_cases),
            )
        )
        analyses = (await self._db.execute(stmt)).scalars().all()
        updated = 0
        for analysis in analyses:
            hierarchy = dict(analysis.hierarchy or {})
            entities = dict(analysis.entities or {})

            if "case" in hierarchy:
                hierarchy.pop("case", None)
                analysis.hierarchy = hierarchy
                flag_modified(analysis, "hierarchy")

            removed_entity = False
            for key in ("address", "address_hierarchy"):
                if key in entities:
                    entities.pop(key, None)
                    removed_entity = True
            if removed_entity:
                analysis.entities = entities
                flag_modified(analysis, "entities")

            updated += 1

        if updated:
            await self._db.commit()

        return {"cases": normalized_cases, "updated_analyses": updated}

    def cache_snapshot(self) -> dict:
        """Geo-кэш для чтения: разбирается один раз, пока файл не изменился.

        Список болей просит снимок на каждый запрос, а разбор 11 МБ JSON стоит
        около 150 мс. Возвращается общий объект — менять его нельзя, пишущие
        задачи берут свежую копию через ``_load``.
        """

        global _CACHE_SNAPSHOT, _CACHE_SNAPSHOT_KEY
        try:
            stat = self._cache.stat()
        except OSError:
            return {}
        key = (str(self._cache), stat.st_mtime_ns, stat.st_size)
        if _CACHE_SNAPSHOT_KEY != key:
            _CACHE_SNAPSHOT = self._load()
            _CACHE_SNAPSHOT_KEY = key
        return _CACHE_SNAPSHOT

    def cached_geocode_for_context(self, context: LocationContext, cache: dict | None = None) -> dict | None:
        """Координаты из кэша по тому же набору запросов, что использует карта."""
        name = str(context.case_name or "").strip()
        if not name or name.lower() in _SKIP or not is_valid_case_title(name):
            return None
        cache = cache if cache is not None else self._load()
        expected_region, queries = build_geocode_queries(context)
        for query in queries:
            entry = cache.get(f"v2|{query}")
            if not _is_hit(entry):
                continue
            # Записи копились и по старым правилам, когда без региона паблика
            # принимался ответ откуда угодно: так «Трасса 42, 2» осела в кэше
            # с точкой в Туркестане. В записи лежат все поля ответа, поэтому
            # проверяем её заново, не обращаясь к провайдеру.
            point = _point_from_cache_entry(entry)
            if point is not None and not point_in_expected_region(expected_region, point):
                continue
            return entry
        return None

    def cache_status(self) -> dict:
        """Возвращает диагностический статус файлового geo-cache."""

        path = self._cache
        parent = path.parent
        exists = path.exists()
        now = time.time()
        ttl = int(getattr(settings, "GEO_MISS_TTL_SECONDS", 86400))
        status = {
            "path": str(settings.GEO_CACHE_PATH),
            "absolute_path": str(path),
            "exists": exists,
            "parent_exists": parent.exists(),
            "readable": exists and os.access(path, os.R_OK),
            "writable": exists and os.access(path, os.W_OK),
            "parent_writable": parent.exists() and os.access(parent, os.W_OK),
            "size_bytes": path.stat().st_size if exists else None,
            "modified_at": (
                datetime.fromtimestamp(path.stat().st_mtime).isoformat()
                if exists else None
            ),
            "total_entries": 0,
            "hit_entries": 0,
            "miss_entries": 0,
            "stale_miss_entries": 0,
            "malformed_entries": 0,
            "source_breakdown": {},
            "sample_keys": [],
            "read_error": None,
            "max_new_per_request": int(getattr(settings, "GEO_MAX_NEW_PER_REQUEST", 15)),
            "miss_ttl_seconds": ttl,
            "timeout_seconds": int(getattr(settings, "GEO_TIMEOUT_SECONDS", 15)),
            "providers": {
                "yandex_configured": bool(getattr(settings, "YANDEX_GEOCODER_KEY", "")),
                "dadata_configured": bool(
                    getattr(settings, "DADATA_TOKEN", "")
                    and getattr(settings, "DADATA_SECRET", "")
                ),
                "priority": ["yandex", "dadata"],
            },
        }
        if not exists:
            return status
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            status["read_error"] = str(exc)
            return status
        if not isinstance(data, dict):
            status["read_error"] = f"Ожидался JSON object, получен {type(data).__name__}"
            return status
        status["total_entries"] = len(data)
        status["sample_keys"] = sorted(str(key) for key in data.keys())[:10]
        for entry in data.values():
            if _is_hit(entry):
                status["hit_entries"] += 1
                source = str(entry.get("source") or "unknown").strip() or "unknown"
                status["source_breakdown"][source] = status["source_breakdown"].get(source, 0) + 1
            elif isinstance(entry, dict) and "_miss" in entry:
                status["miss_entries"] += 1
                if not _miss_fresh(entry, now, ttl):
                    status["stale_miss_entries"] += 1
            else:
                status["malformed_entries"] += 1
        return status

    def rotate_cache(self) -> dict:
        """Переименовывает текущий geo-cache в backup с timestamp."""

        path = self._cache
        if not path.exists():
            return {
                "rotated": False,
                "previous_path": str(path),
                "backup_path": None,
                "message": "Geo-cache файл не найден, ротировать нечего",
                "status_after": self.cache_status(),
            }
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.stem}.{timestamp}{path.suffix}.bak")
        suffix = 1
        while backup.exists():
            backup = path.with_name(f"{path.stem}.{timestamp}-{suffix}{path.suffix}.bak")
            suffix += 1
        path.rename(backup)
        return {
            "rotated": True,
            "previous_path": str(path),
            "backup_path": str(backup),
            "message": "Geo-cache переименован, новый файл будет создан при следующем геокодинге",
            "status_after": self.cache_status(),
        }

    async def _case_counts(self, user: User, since: datetime | None,
                           link_id: uuid.UUID | None, problem_type: str | None,
                           limit: int | None,
                           municipality_name: str | None = None) -> list[dict]:
        sql_text = f"""
            SELECT json_extract_path_text(ca.hierarchy,'case') AS case_name,
                   lower(coalesce(json_extract_path_text(ca.hierarchy,'category'),'')) AS cat,
                   coalesce(reg.name, '') AS public_region,
                   coalesce(p.name, '') AS public_name,
                   coalesce(psl.title, '') AS source_title,
                   (array_agg(cm.text ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_comment,
                   (array_agg(json_extract_path_text(ca.entities,'address') ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_address,
                   (array_agg(json_extract_path(ca.entities,'address_hierarchy') ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_address_hierarchy,
                   count(DISTINCT (pub.id::text || ':' || coalesce(cm.external_id, cm.id::text))) AS c
            FROM comment_analysis ca
            JOIN comments cm ON cm.id = ca.comment_id
            JOIN publications pub ON pub.id = cm.publication_id
            JOIN public_social_links psl ON psl.id = pub.public_social_link_id
            JOIN publics p ON p.id = psl.public_id
            LEFT JOIN regions reg ON reg.id = p.region_id
            WHERE p.organization_id = :org
              AND cm.is_deleted = false
              AND ca.classification_state = 'done'
              AND ca.relevance = 'relevant'
              AND ca.message_type IN ('complaint', 'sarcasm', 'request')
              AND coalesce(ca.is_official_response, false) = false
              AND (cm.author_external_id IS NULL OR cm.author_external_id NOT LIKE '-%')
              AND coalesce(json_extract_path_text(ca.hierarchy,'case'),'') <> ''
              AND (CAST(:since AS timestamptz) IS NULL
                   OR coalesce(cm.comment_date, cm.created_at) >= CAST(:since AS timestamptz))
              AND (CAST(:link AS uuid) IS NULL OR psl.id = CAST(:link AS uuid))
              {raw_address_municipality_clause()}
              AND (
                  CAST(:problem_type AS text) IS NULL
                  OR (
                      CAST(:problem_type AS text) = :other_problem_type
                      AND NOT (
                          lower(coalesce(json_extract_path_text(ca.hierarchy,'category'),'')) = ANY(:standard_problem_categories)
                      )
                  )
                  OR lower(coalesce(json_extract_path_text(ca.hierarchy,'category'),'')) = lower(CAST(:problem_type AS text))
              )
            GROUP BY 1, 2, 3, 4, 5 ORDER BY c DESC
        """
        params = {
            "org": user.organization_id, "since": since, "link": link_id,
            "problem_type": problem_type,
            "other_problem_type": OTHER_PROBLEM_TYPE,
            "standard_problem_categories": list(STANDARD_PROBLEM_CATEGORIES),
            **raw_municipality_params(municipality_name),
        }
        if limit is not None:
            sql_text += " LIMIT :lim"
            params["lim"] = limit
        rows = (await self._db.execute(text(sql_text), params)).all()
        return [
            {
                "case_name": r.case_name,
                "cat": r.cat,
                "count": int(r.c),
                "public_region": r.public_region or "",
                "public_name": r.public_name or "",
                "source_title": r.source_title or "",
                "sample_comment": r.sample_comment or "",
                "sample_address": r.sample_address or "",
                "sample_address_hierarchy": r.sample_address_hierarchy,
            }
            for r in rows
        ]

    async def geocoding_stats(self, *, organization_id: uuid.UUID | None = None) -> dict:
        """Считает адресные кейсы карты, покрытые текущим geo-кэшем.

        Только чтение, и намеренно: открытие страницы настроек не должно дёргать
        Яндекс или DaData.
        """

        sql = text("""
            SELECT json_extract_path_text(ca.hierarchy,'case') AS case_name,
                   coalesce(reg.name, '') AS public_region,
                   coalesce(p.name, '') AS public_name,
                   coalesce(psl.title, '') AS source_title,
                   (array_agg(cm.text ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_comment,
                   (array_agg(json_extract_path_text(ca.entities,'address') ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_address,
                   (array_agg(json_extract_path(ca.entities,'address_hierarchy') ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_address_hierarchy,
                   count(DISTINCT (pub.id::text || ':' || coalesce(cm.external_id, cm.id::text))) AS c
            FROM comment_analysis ca
            JOIN comments cm ON cm.id = ca.comment_id
            JOIN publications pub ON pub.id = cm.publication_id
            JOIN public_social_links psl ON psl.id = pub.public_social_link_id
            JOIN publics p ON p.id = psl.public_id
            LEFT JOIN regions reg ON reg.id = p.region_id
            WHERE cm.is_deleted = false
              AND ca.classification_state = 'done'
              AND ca.relevance = 'relevant'
              AND ca.message_type IN ('complaint', 'sarcasm', 'request')
              AND coalesce(ca.is_official_response, false) = false
              AND (cm.author_external_id IS NULL OR cm.author_external_id NOT LIKE '-%')
              AND coalesce(json_extract_path_text(ca.hierarchy,'case'),'') <> ''
              AND (CAST(:org AS uuid) IS NULL OR p.organization_id = CAST(:org AS uuid))
            GROUP BY 1, 2, 3, 4
        """)
        rows = (await self._db.execute(sql, {"org": organization_id})).all()
        cache = self._load()
        status = self.cache_status()
        total_cases = 0
        geocoded_cases = 0
        not_geocoded_cases = 0
        rejected_cases = 0
        untried_cases = 0
        unasked_cases = 0
        skipped_invalid_cases = 0
        total_mentions = 0
        geocoded_mentions = 0
        not_geocoded_mentions = 0
        rejected_mentions = 0
        untried_mentions = 0

        for row in rows:
            name = str(row.case_name or "").strip()
            mentions = int(row.c or 0)
            if not name or name.lower() in _SKIP or not is_valid_case_title(name):
                skipped_invalid_cases += 1
                continue
            context = LocationContext(
                case_name=name,
                public_region=str(row.public_region or ""),
                public_name=str(row.public_name or ""),
                source_title=str(row.source_title or ""),
                comment_text=str(row.sample_comment or ""),
                address=str(row.sample_address or ""),
                address_hierarchy=_json_object(row.sample_address_hierarchy),
            )
            _, queries = build_geocode_queries(context)
            cache_entries = [cache.get(f"v2|{query}") for query in queries]
            has_geo = any(_is_hit(entry) for entry in cache_entries)
            has_attempt = any(entry is not None for entry in cache_entries)
            total_cases += 1
            total_mentions += mentions
            if has_geo:
                geocoded_cases += 1
                geocoded_mentions += mentions
            elif has_attempt:
                not_geocoded_cases += 1
                rejected_cases += 1
                not_geocoded_mentions += mentions
                rejected_mentions += mentions
                # Внутри отклонённых: те, где провайдер вообще не ответил —
                # кончилась норма ключей или сорвалась сеть. Их стоит
                # переспросить, в отличие от честных отказов.
                if any(_miss_without_answer(entry) for entry in cache_entries):
                    unasked_cases += 1
            else:
                not_geocoded_cases += 1
                untried_cases += 1
                not_geocoded_mentions += mentions
                untried_mentions += mentions

        return {
            "total_cases": total_cases,
            "geocoded_cases": geocoded_cases,
            "not_geocoded_cases": not_geocoded_cases,
            "rejected_cases": rejected_cases,
            "untried_cases": untried_cases,
            "unasked_cases": unasked_cases,
            "skipped_invalid_cases": skipped_invalid_cases,
            "total_mentions": total_mentions,
            "geocoded_mentions": geocoded_mentions,
            "not_geocoded_mentions": not_geocoded_mentions,
            "rejected_mentions": rejected_mentions,
            "untried_mentions": untried_mentions,
            "cache_hit_entries": int(status.get("hit_entries") or 0),
            "cache_miss_entries": int(status.get("miss_entries") or 0),
            "cache_total_entries": int(status.get("total_entries") or 0),
            "cache_read_error": status.get("read_error"),
            "cache_modified_at": status.get("modified_at"),
        }

    async def _load_geocoder_keys(self) -> None:
        """Загружает ключи геокодера из БД в пул процесса.

        После рестарта контейнера пул пуст, поэтому каждая задача геокодинга
        загружает ключи сама. Ошибка загрузки задачу не роняет: пул остаётся
        на значениях из .env.
        """
        from backend.app.runtime_settings import get_yandex_geocoder_keys

        try:
            set_runtime_keys(await get_yandex_geocoder_keys(self._db))
        except Exception:  # noqa: BLE001
            # Откат обязателен: без него сессия остаётся в оборванной
            # транзакции и роняет все последующие запросы задачи.
            await self._db.rollback()
            logging.getLogger(__name__).warning(
                "Не удалось загрузить ключи геокодера из БД, работаю на .env",
                exc_info=True,
            )

    async def backfill_missing_geocodes(
        self,
        *,
        organization_id: uuid.UUID | None = None,
        max_new: int | None = None,
        retry_fresh_misses: bool = False,
        only_revalidated: bool = False,
        only_untried: bool = False,
        only_unasked: bool = False,
        progress=None,
    ) -> dict:
        """Догревает geo-кэш для старых кейсов карты, у которых ещё нет попадания."""

        await self._load_geocoder_keys()

        sql = text("""
            SELECT json_extract_path_text(ca.hierarchy,'case') AS case_name,
                   coalesce(reg.name, '') AS public_region,
                   coalesce(p.name, '') AS public_name,
                   coalesce(psl.title, '') AS source_title,
                   (array_agg(cm.text ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_comment,
                   (array_agg(json_extract_path_text(ca.entities,'address') ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_address,
                   (array_agg(json_extract_path(ca.entities,'address_hierarchy') ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_address_hierarchy,
                   count(DISTINCT (pub.id::text || ':' || coalesce(cm.external_id, cm.id::text))) AS c
            FROM comment_analysis ca
            JOIN comments cm ON cm.id = ca.comment_id
            JOIN publications pub ON pub.id = cm.publication_id
            JOIN public_social_links psl ON psl.id = pub.public_social_link_id
            JOIN publics p ON p.id = psl.public_id
            LEFT JOIN regions reg ON reg.id = p.region_id
            WHERE cm.is_deleted = false
              AND ca.classification_state = 'done'
              AND ca.relevance = 'relevant'
              AND ca.message_type IN ('complaint', 'sarcasm', 'request')
              AND coalesce(ca.is_official_response, false) = false
              AND (cm.author_external_id IS NULL OR cm.author_external_id NOT LIKE '-%')
              AND coalesce(json_extract_path_text(ca.hierarchy,'case'),'') <> ''
              AND (CAST(:org AS uuid) IS NULL OR p.organization_id = CAST(:org AS uuid))
            GROUP BY 1, 2, 3, 4
            ORDER BY c DESC
        """)
        rows = (await self._db.execute(sql, {"org": organization_id})).all()
        cache = self._load()
        dirty = False
        now = time.time()
        ttl = float(getattr(settings, "GEO_MISS_TTL_SECONDS", 86400))
        # Отказ, поставленный пересмотром, всегда свежий — иначе точечный добор
        # пропустил бы ровно то, ради чего запускается.
        retry_fresh_misses = retry_fresh_misses or only_revalidated or only_unasked
        budget = max_new
        timeout = int(getattr(settings, "GEO_TIMEOUT_SECONDS", 15))
        stats = {
            "considered": 0,
            "already_cached": 0,
            "requests_made": 0,
            "geocoded": 0,
            "missed": 0,
            "fresh_miss_skipped": 0,
            "invalid_skipped": 0,
            "budget_exhausted": 0,
        }
        targets = []

        for row in rows:
            name = str(row.case_name or "").strip()
            if not name or name.lower() in _SKIP or not is_valid_case_title(name):
                stats["invalid_skipped"] += 1
                continue

            stats["considered"] += 1
            context = LocationContext(
                case_name=name,
                public_region=str(row.public_region or ""),
                public_name=str(row.public_name or ""),
                source_title=str(row.source_title or ""),
                comment_text=str(row.sample_comment or ""),
                address=str(row.sample_address or ""),
                address_hierarchy=_json_object(row.sample_address_hierarchy),
            )
            expected_region, queries = build_geocode_queries(context)
            cache_entries = [cache.get(f"v2|{query}") for query in queries]
            if any(_is_hit(entry) for entry in cache_entries):
                stats["already_cached"] += 1
                continue
            # Точечный добор после пересмотра: у этих кейсов точку сняли как
            # уехавшую в чужой город, а по-новому — с городом площадки в
            # запросе — их ещё не спрашивали. Остальные отказы переспрашивать
            # незачем, стратегия для них не менялась.
            if only_revalidated and not any(
                isinstance(entry, dict) and entry.get("revalidated")
                for entry in cache_entries
            ):
                continue
            # Только те, кого геокодер не видел ни разу: у остальных отказ уже
            # получен текущей стратегией, повтор даст тот же ответ.
            if only_untried and any(entry is not None for entry in cache_entries):
                continue
            # Отказы, где ответа не было вовсе: кончилась норма ключей или
            # сорвалась сеть. Пустых ответов от Яндекса на наших запросах
            # практически не бывает, так что это именно «не смогли спросить».
            if only_unasked and not any(_miss_without_answer(entry) for entry in cache_entries):
                continue
            targets.append((name, context, expected_region, queries))

        total = len(targets)
        done = 0
        if progress is not None:
            await progress.update(
                total=total,
                done=0,
                message=f"Догеокодинг адресных кейсов: 0/{total}",
            )

        for name, context, expected_region, queries in targets:
            if progress is not None:
                progress.raise_if_cancelled()
            made_request = False
            blocked_by_fresh_miss = False
            blocked_by_budget = False
            accepted = False

            # Справочник объектов идёт первым: он точнее геокодера на школах,
            # больницах и остановках и не тратит обращений.
            directory_point = _object_directory_point(context) if queries else None
            if directory_point is not None:
                geo_payload = {
                    "lat": directory_point.lat,
                    "lon": directory_point.lon,
                    "region": directory_point.region,
                    "municipality": directory_point.municipality,
                    "locality": directory_point.locality,
                    "district": directory_point.district,
                    "source": directory_point.source,
                    "precision": directory_point.precision,
                    "provider_name": directory_point.provider_name,
                    "provider_description": directory_point.provider_description,
                    "provider_kind": directory_point.provider_kind,
                    "provider_text": directory_point.provider_text,
                    "query": queries[0],
                    "case_name": name,
                    "confidence": "directory",
                    "agreed_by": ["enisey_gis"],
                }
                cache[f"v2|{queries[0]}"] = {
                    **geo_payload,
                    "display_title": address_display_title(name, geo_payload),
                    "canonical_title": address_canonical_title(name, geo_payload),
                }
                dirty = True
                stats["geocoded"] += 1
                done += 1
                if progress is not None:
                    await progress.update(
                        total=total,
                        done=done,
                        message=(
                            f"Догеокодинг адресных кейсов: осталось {max(0, total - done)}; "
                            f"найдено {stats['geocoded']}, miss {stats['missed']}"
                        ),
                    )
                continue

            for query in queries:
                cache_key = f"v2|{query}"
                cached = cache.get(cache_key)
                if _is_hit(cached):
                    accepted = True
                    stats["already_cached"] += 1
                    break
                if (
                    _miss_fresh(cached, now, ttl)
                    and not retry_fresh_misses
                ):
                    blocked_by_fresh_miss = True
                    continue
                if budget is not None and budget <= 0:
                    blocked_by_budget = True
                    continue
                # Суточная норма ключей выбрана: геокодер вернёт пусто, и кейс
                # осел бы в кэше ложным отказом. Останавливаемся, остаток
                # доберём завтра.
                if not has_capacity():
                    blocked_by_budget = True
                    continue

                p, agreed_by = await asyncio.to_thread(_resolve_point, query, timeout)
                made_request = True
                stats["requests_made"] += 1
                if p and accept_geocode_result(context, query, expected_region, p):
                    geo_payload = {
                        "lat": p.lat,
                        "lon": p.lon,
                        "region": p.region,
                        "municipality": p.municipality,
                        "locality": p.locality,
                        "district": p.district,
                        "source": p.source,
                        "precision": p.precision,
                        "provider_name": p.provider_name,
                        "provider_description": p.provider_description,
                        "provider_kind": p.provider_kind,
                        "provider_text": p.provider_text,
                        "query": query,
                        "case_name": name,
                        "confidence": "consensus" if len(agreed_by) > 1 else "single",
                        "agreed_by": agreed_by,
                    }
                    cache[cache_key] = {
                        **geo_payload,
                        "display_title": address_display_title(name, geo_payload),
                        "canonical_title": address_canonical_title(name, geo_payload),
                    }
                    accepted = True
                else:
                    cache[cache_key] = {
                        "_miss": now,
                        "source": p.source if p else "none",
                        "query": query,
                        "case_name": name,
                        "confidence": "consensus" if len(agreed_by) > 1 else "single",
                        "agreed_by": agreed_by,
                    }
                dirty = True
                if budget is not None:
                    budget -= 1
                if accepted:
                    stats["geocoded"] += 1
                    break

            if made_request and not accepted:
                stats["missed"] += 1
            elif blocked_by_budget and not accepted:
                stats["budget_exhausted"] += 1
            elif blocked_by_fresh_miss and not accepted:
                stats["fresh_miss_skipped"] += 1

            done += 1
            if progress is not None:
                remaining = max(0, total - done)
                await progress.update(
                    total=total,
                    done=done,
                    message=(
                        f"Догеокодинг адресных кейсов: осталось {remaining}; "
                        f"найдено {stats['geocoded']}, miss {stats['missed']}"
                    ),
                )

            if blocked_by_budget:
                break

        if dirty:
            self._save(cache)
        stats["remaining"] = max(0, total - done)
        return stats

    def restore_revalidated_points(self) -> dict:
        """Возвращает точки, снятые пересмотром: каждая лежит в записи под ``was``."""

        cache = self._load()
        restored = 0
        for key, entry in list(cache.items()):
            if not isinstance(entry, dict) or not entry.get("revalidated"):
                continue
            previous = entry.get("was")
            if _is_hit(previous):
                cache[key] = previous
                restored += 1
        if restored:
            self._save(cache)
        return {"restored_points": restored}

    async def revalidate_geocode_cache(
        self,
        *,
        organization_id: uuid.UUID | None = None,
        apply: bool = False,
        sample_limit: int = 30,
        progress=None,
    ) -> dict:
        """Перепроверяет уже найденные точки текущей отбраковкой, без запросов.

        В кэше лежит весь ответ геокодера, а не только координаты, поэтому
        `accept_geocode_result` можно прогнать заново офлайн. Это единственный
        способ пересмотреть точки, принятые прежней логикой: очистка кэша стоит
        13 тысяч обращений и нескольких суток, а здесь — минуты и ноль квоты.

        По умолчанию только считает. Записывает изменения при ``apply=True``:
        не прошедшая проверку точка становится miss с тем же составом полей,
        что и при обычном отказе, — повторно спрашивать её незачем, ответ
        геокодера не изменится.
        """

        sql = text("""
            SELECT json_extract_path_text(ca.hierarchy,'case') AS case_name,
                   coalesce(reg.name, '') AS public_region,
                   coalesce(p.name, '') AS public_name,
                   coalesce(psl.title, '') AS source_title,
                   (array_agg(cm.text ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_comment,
                   (array_agg(json_extract_path_text(ca.entities,'address') ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_address,
                   (array_agg(json_extract_path(ca.entities,'address_hierarchy') ORDER BY coalesce(cm.comment_date, cm.created_at) DESC))[1] AS sample_address_hierarchy,
                   count(DISTINCT (pub.id::text || ':' || coalesce(cm.external_id, cm.id::text))) AS c
            FROM comment_analysis ca
            JOIN comments cm ON cm.id = ca.comment_id
            JOIN publications pub ON pub.id = cm.publication_id
            JOIN public_social_links psl ON psl.id = pub.public_social_link_id
            JOIN publics p ON p.id = psl.public_id
            LEFT JOIN regions reg ON reg.id = p.region_id
            WHERE cm.is_deleted = false
              AND ca.classification_state = 'done'
              AND ca.relevance = 'relevant'
              AND ca.message_type IN ('complaint', 'sarcasm', 'request')
              AND coalesce(ca.is_official_response, false) = false
              AND (cm.author_external_id IS NULL OR cm.author_external_id NOT LIKE '-%')
              AND coalesce(json_extract_path_text(ca.hierarchy,'case'),'') <> ''
              AND (CAST(:org AS uuid) IS NULL OR p.organization_id = CAST(:org AS uuid))
            GROUP BY 1, 2, 3, 4
            ORDER BY c DESC
        """)
        rows = (await self._db.execute(sql, {"org": organization_id})).all()
        cache = self._load()
        dirty = False
        now = time.time()
        stats = {
            "cases": 0,
            "checked_points": 0,
            "kept_points": 0,
            "dropped_points": 0,
            "cases_losing_point": 0,
            "applied": apply,
        }
        samples: list[dict] = []

        total = len(rows)
        done = 0
        try:
            for row in rows:
                name = str(row.case_name or "").strip()
                if not name or name.lower() in _SKIP or not is_valid_case_title(name):
                    continue

                stats["cases"] += 1
                context = LocationContext(
                    case_name=name,
                    public_region=str(row.public_region or ""),
                    public_name=str(row.public_name or ""),
                    source_title=str(row.source_title or ""),
                    comment_text=str(row.sample_comment or ""),
                    address=str(row.sample_address or ""),
                    address_hierarchy=_json_object(row.sample_address_hierarchy),
                )
                expected_region, queries = build_geocode_queries(context)
                had_hit = False
                keeps_hit = False

                for query in queries:
                    cache_key = f"v2|{query}"
                    entry = cache.get(cache_key)
                    if not _is_hit(entry):
                        continue
                    had_hit = True
                    stats["checked_points"] += 1
                    point = _point_from_cache_entry(entry)
                    # Судим только по защите города: она опирается на координаты
                    # и населённый пункт, которые есть в любой записи. Полная
                    # отбраковка смотрит ещё и на служебные поля геокодера, а в
                    # старых записях их может не быть — и тогда снимались бы
                    # верные точки («город Сосновоборск» без provider_kind).
                    if point is None or not point_contradicts_public_city(context, point):
                        stats["kept_points"] += 1
                        keeps_hit = True
                        continue

                    stats["dropped_points"] += 1
                    if len(samples) < sample_limit:
                        samples.append({
                            "case_name": name,
                            "public_name": context.public_name,
                            "query": query,
                            "found": str(entry.get("provider_text") or ""),
                            "locality": str(entry.get("locality") or ""),
                            "lat": entry.get("lat"),
                            "lon": entry.get("lon"),
                        })
                    if apply:
                        cache[cache_key] = {
                            "_miss": now,
                            "source": str(entry.get("source") or "none"),
                            "query": query,
                            "case_name": name,
                            "confidence": str(entry.get("confidence") or "single"),
                            "agreed_by": entry.get("agreed_by") or [],
                            "revalidated": True,
                            # Прежняя точка целиком: файл кэша перезаписывается
                            # без бэкапа, а снятие должно быть обратимым.
                            "was": entry,
                        }
                        dirty = True

                if had_hit and not keeps_hit:
                    stats["cases_losing_point"] += 1

                done += 1
                if progress is not None and done % 100 == 0:
                    progress.raise_if_cancelled()
                    await progress.update(
                        total=total,
                        done=done,
                        message=(
                            f"Пересмотр точек: {done}/{total}; "
                            f"снято {stats['dropped_points']}"
                        ),
                    )
        finally:
            # Сохраняем даже при отмене: пересмотр идёт без обращений к
            # геокодеру, терять уже проделанную работу незачем.
            if dirty:
                self._save(cache)

        stats["samples"] = samples
        return stats

    async def warm_geocode_for_comments(
        self,
        comment_ids: list[uuid.UUID],
        *,
        max_new: int | None = None,
    ) -> dict:
        """Греет geo-кэш по свежим комментариям, не дожидаясь открытия карты.

        Стратегия запросов и правила приёмки те же, что у карты. Пишется только
        файловый кэш, comment_analysis не трогается.
        """

        if not comment_ids:
            return {
                "considered": 0,
                "already_cached": 0,
                "geocoded": 0,
                "missed": 0,
                "skipped": 0,
                "budget_exhausted": 0,
            }

        await self._load_geocoder_keys()

        sql = text("""
            SELECT cm.id AS comment_id,
                   json_extract_path_text(ca.hierarchy,'case') AS case_name,
                   coalesce(reg.name, '') AS public_region,
                   coalesce(p.name, '') AS public_name,
                   coalesce(psl.title, '') AS source_title,
                   cm.text AS sample_comment,
                   json_extract_path_text(ca.entities,'address') AS sample_address,
                   json_extract_path(ca.entities,'address_hierarchy') AS sample_address_hierarchy
            FROM comment_analysis ca
            JOIN comments cm ON cm.id = ca.comment_id
            JOIN publications pub ON pub.id = cm.publication_id
            JOIN public_social_links psl ON psl.id = pub.public_social_link_id
            JOIN publics p ON p.id = psl.public_id
            LEFT JOIN regions reg ON reg.id = p.region_id
            WHERE cm.id IN :comment_ids
              AND cm.is_deleted = false
              AND ca.classification_state = 'done'
              AND ca.relevance = 'relevant'
              AND ca.message_type IN ('complaint', 'sarcasm', 'request')
              AND coalesce(ca.is_official_response, false) = false
              AND (cm.author_external_id IS NULL OR cm.author_external_id NOT LIKE '-%')
              AND coalesce(json_extract_path_text(ca.hierarchy,'case'),'') <> ''
        """).bindparams(bindparam("comment_ids", expanding=True))
        rows = (
            await self._db.execute(
                sql,
                {"comment_ids": comment_ids},
            )
        ).all()

        cache = self._load()
        dirty = False
        now = time.time()
        ttl = float(getattr(settings, "GEO_MISS_TTL_SECONDS", 86400))
        budget = max_new
        if budget is None:
            budget = int(getattr(settings, "GEO_MAX_NEW_PER_REQUEST", 15))
        timeout = int(getattr(settings, "GEO_TIMEOUT_SECONDS", 15))
        stats = {
            "considered": 0,
            "already_cached": 0,
            "geocoded": 0,
            "missed": 0,
            "skipped": 0,
            "budget_exhausted": 0,
        }

        for row in rows:
            name = str(row.case_name or "").strip()
            if not name or name.lower() in _SKIP or not is_valid_case_title(name):
                stats["skipped"] += 1
                continue

            stats["considered"] += 1
            context = LocationContext(
                case_name=name,
                public_region=str(row.public_region or ""),
                public_name=str(row.public_name or ""),
                source_title=str(row.source_title or ""),
                comment_text=str(row.sample_comment or ""),
                address=str(row.sample_address or ""),
                address_hierarchy=_json_object(row.sample_address_hierarchy),
            )
            expected_region, queries = build_geocode_queries(context)
            already_tried = False
            entry = None
            exhausted = False

            for query in queries:
                cache_key = f"v2|{query}"
                candidate_entry = cache.get(cache_key)
                if _is_hit(candidate_entry):
                    entry = candidate_entry
                    stats["already_cached"] += 1
                    break
                if _miss_fresh(candidate_entry, now, ttl):
                    already_tried = True
                    continue
                if budget <= 0:
                    exhausted = True
                    continue
                # См. догеокодинг: без запаса у ключей запрос не уходит, и кейс
                # записался бы ложным отказом.
                if not has_capacity():
                    exhausted = True
                    continue

                p, agreed_by = await asyncio.to_thread(_resolve_point, query, timeout)
                already_tried = True
                if p and accept_geocode_result(context, query, expected_region, p):
                    geo_payload = {
                        "lat": p.lat,
                        "lon": p.lon,
                        "region": p.region,
                        "municipality": p.municipality,
                        "locality": p.locality,
                        "district": p.district,
                        "source": p.source,
                        "precision": p.precision,
                        "provider_name": p.provider_name,
                        "provider_description": p.provider_description,
                        "provider_kind": p.provider_kind,
                        "provider_text": p.provider_text,
                        "query": query,
                        "case_name": name,
                        "confidence": "consensus" if len(agreed_by) > 1 else "single",
                        "agreed_by": agreed_by,
                    }
                    cache[cache_key] = {
                        **geo_payload,
                        "display_title": address_display_title(name, geo_payload),
                        "canonical_title": address_canonical_title(name, geo_payload),
                    }
                    entry = cache[cache_key]
                else:
                    cache[cache_key] = {
                        "_miss": now,
                        "source": p.source if p else "none",
                        "query": query,
                        "case_name": name,
                        "confidence": "consensus" if len(agreed_by) > 1 else "single",
                        "agreed_by": agreed_by,
                    }
                dirty = True
                budget -= 1
                if entry:
                    stats["geocoded"] += 1
                    break

            if entry:
                continue
            if exhausted and not already_tried:
                stats["budget_exhausted"] += 1
            elif exhausted:
                stats["budget_exhausted"] += 1
            else:
                stats["missed"] += 1

        if dirty:
            self._save(cache)
        return stats

    async def points(self, user: User, *, since: datetime | None = None,
                     link_id: uuid.UUID | None = None, problem_type: str | None = None,
                     municipality_name: str | None = None,
                     limit: int | None = None) -> list[dict]:
        rows = await self._case_counts(
            user,
            since,
            link_id,
            problem_type,
            limit,
            municipality_name=municipality_name,
        )
        cache = self._load()
        dirty = False
        agg: dict[tuple, dict] = {}
        for row in rows:
            case_name = str(row.get("case_name") or "")
            cnt = int(row.get("count") or 0)
            name = (case_name or "").strip()
            if not name or name.lower() in _SKIP or not is_valid_case_title(name):
                continue
            context = LocationContext(
                case_name=name,
                public_region=str(row.get("public_region") or ""),
                public_name=str(row.get("public_name") or ""),
                source_title=str(row.get("source_title") or ""),
                comment_text=str(row.get("sample_comment") or ""),
                address=str(row.get("sample_address") or ""),
                address_hierarchy=_json_object(row.get("sample_address_hierarchy")),
            )
            _, queries = build_geocode_queries(context)
            entry = None
            for query in queries:
                cache_key = f"v2|{query}"
                candidate_entry = cache.get(cache_key)
                if _is_hit(candidate_entry):
                    entry = candidate_entry
                    break
            geo = entry if _is_hit(entry) else None
            if not geo:
                continue
            if not geo.get("display_title"):
                geo["display_title"] = address_display_title(name, geo)
                geo["canonical_title"] = address_canonical_title(name, geo)
                dirty = True
            key = (round(geo["lat"], 3), round(geo["lon"], 3))
            region = geo.get("region", "")
            municipality = geo.get("municipality", "") or geo.get("district", "")
            locality = geo.get("locality", "")
            pt = agg.setdefault(key, {
                "name": geo.get("display_title") or name,
                "lat": geo["lat"],
                "lon": geo["lon"],
                "region": region,
                "municipality": municipality,
                "locality": locality,
                "district": geo.get("district", "") or municipality or locality or region,
                "count": 0,
                "cases": [],
            })
            pt["count"] += cnt
            if name not in pt["cases"]:
                pt["cases"].append(name)
        if dirty:
            self._save(cache)
        return sorted(agg.values(), key=lambda x: x["count"], reverse=True)

    async def case_comments(self, user: User, cases: list[str], *, since: datetime | None = None,
                            link_id: PublicSocialLinkFilter = None, problem_type: str | None = None,
                            municipality_name: str | None = None,
                            limit: int = 100) -> list[dict]:
        """Комментарии, относящиеся к адресным кейсам точки (для drill-down на карте)."""
        if not cases:
            return []
        link_ids = normalize_public_social_link_ids(link_id)
        link_clause = "AND psl.id IN :link_ids" if link_ids else ""
        sql = text(f"""
            WITH ranked AS (
                SELECT cm.id AS comment_id,
                       cm.text,
                       cm.external_id,
                       cm.comment_date,
                       pub.url AS pub_url,
                       ca.sentiment AS sentiment, p.name AS public_name,
                       json_extract_path_text(ca.hierarchy,'category') AS category,
                       json_extract_path_text(ca.hierarchy,'subcategory') AS subcategory,
                       resp.response_id AS official_response_id,
                       resp.response_text AS official_response_text,
                       resp.response_external_id AS official_response_external_id,
                       resp.response_date AS official_response_date,
                       row_number() OVER (
                           PARTITION BY pub.id, coalesce(cm.external_id, cm.id::text)
                           ORDER BY cm.comment_date DESC NULLS LAST, cm.created_at DESC
                       ) AS rn
                FROM comment_analysis ca
                JOIN comments cm ON cm.id = ca.comment_id
                JOIN publications pub ON pub.id = cm.publication_id
                JOIN public_social_links psl ON psl.id = pub.public_social_link_id
                JOIN publics p ON p.id = psl.public_id
                LEFT JOIN LATERAL (
                    SELECT rr.id AS response_id,
                           rr.text AS response_text,
                           rr.external_id AS response_external_id,
                           rr.comment_date AS response_date
                    FROM comments rr
                    JOIN comment_analysis ra ON ra.comment_id = rr.id
                    WHERE rr.parent_comment_id = cm.id
                      AND rr.is_deleted = false
                      AND ra.is_official_response = true
                      AND length(regexp_replace(
                          regexp_replace(coalesce(rr.text, ''),
                              '\\[(id|club|public|event)[0-9]+\\|[^\\]]+\\]', '', 'gi'),
                          '[[:space:][:punct:]]+', '', 'g'
                      )) > 0
                    ORDER BY coalesce(rr.comment_date, rr.created_at) ASC NULLS LAST
                    LIMIT 1
                ) resp ON true
                WHERE p.organization_id = :org
                  AND cm.is_deleted = false
                  AND ca.classification_state = 'done'
                  AND ca.relevance = 'relevant'
                  AND ca.message_type IN ('complaint', 'sarcasm', 'request')
                  AND coalesce(ca.is_official_response, false) = false
                  AND (cm.author_external_id IS NULL OR cm.author_external_id NOT LIKE '-%')
                  AND json_extract_path_text(ca.hierarchy,'case') = ANY(:cases)
                  AND (CAST(:since AS timestamptz) IS NULL
                       OR coalesce(cm.comment_date, cm.created_at) >= CAST(:since AS timestamptz))
                  {link_clause}
                  {raw_comment_municipality_clause()}
                  AND (
                      CAST(:problem_type AS text) IS NULL
                      OR (
                          CAST(:problem_type AS text) = :other_problem_type
                          AND NOT (
                              lower(coalesce(json_extract_path_text(ca.hierarchy,'category'),'')) = ANY(:standard_problem_categories)
                          )
                      )
                      OR lower(coalesce(json_extract_path_text(ca.hierarchy,'category'),'')) = lower(CAST(:problem_type AS text))
                  )
            )
            SELECT comment_id,
                   text,
                   external_id,
                   comment_date,
                   pub_url,
                   sentiment,
                   public_name,
                   category,
                   subcategory,
                   official_response_id,
                   official_response_text,
                   official_response_external_id,
                   official_response_date
            FROM ranked
            WHERE rn = 1
            ORDER BY comment_date DESC NULLS LAST
            LIMIT :lim
        """)
        params = {
            "org": user.organization_id, "cases": cases,
            "since": since,
            "problem_type": problem_type,
            "other_problem_type": OTHER_PROBLEM_TYPE,
            "standard_problem_categories": list(STANDARD_PROBLEM_CATEGORIES),
            "lim": limit,
            **raw_municipality_params(municipality_name),
        }
        if link_ids:
            sql = sql.bindparams(bindparam("link_ids", expanding=True))
            params["link_ids"] = link_ids
        rows = (await self._db.execute(sql, params)).all()
        return [{
            "text": r.text,
            "date": r.comment_date.isoformat() if r.comment_date else None,
            "url": r.pub_url,
            "comment_url": vk_comment_url(r.pub_url, r.external_id),
            "sentiment": str(r.sentiment or ""), "public": r.public_name,
            "category": r.category or "", "subcategory": r.subcategory or "",
            "has_official_response": bool(r.official_response_id),
            "official_response_url": vk_comment_url(r.pub_url, r.official_response_external_id),
            "official_response_text": r.official_response_text or None,
            "official_response_date": r.official_response_date.isoformat() if r.official_response_date else None,
        } for r in rows]
