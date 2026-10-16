r"""Debug one comment through LLM classification and map geocoding.

Usage examples:
    .venv\Scripts\python.exe tools\debug_comment_location.py "На ул. Ленина 12 яма"
    .venv\Scripts\python.exe tools\debug_comment_location.py --show-raw "..."
    .venv\Scripts\python.exe tools\debug_comment_location.py --json "..."

The script shows the production path:
comment text -> LLM analysis -> apply_llm_analysis normalization -> map eligibility.

Then it runs an experimental tool-only path:
comment text -> strict LLM address hierarchy -> direct geocoder query from larger
to smaller address parts. This direct geocoder does not prepend Krasnoyarsk Krai.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError  # noqa: E402

from backend.app.config import settings  # noqa: E402
from backend.db.enums import RelevanceEnum  # noqa: E402
from backend.modules.analytics.services.comment_analysis_service import apply_llm_analysis  # noqa: E402
from backend.modules.analytics.utils.address_normalizer import (  # noqa: E402
    address_canonical_title,
    address_display_title,
)
from backend.modules.analytics.utils.case_extractor import (  # noqa: E402
    case_location_key,
    is_valid_case_title,
)
from backend.modules.llm import analysis_prompt  # noqa: E402
from backend.modules.llm.clients import create_llm_client, get_default_llm_model  # noqa: E402
from backend.modules.llm.interfaces import LLMError  # noqa: E402
from backend.modules.llm.repositories.prompt_repository import FilePromptRepository  # noqa: E402
from backend.modules.llm.services.comment_analysis_parser import CommentAnalysisParser  # noqa: E402
from backend.modules.llm.utils.json_response import extract_json_object  # noqa: E402


MAP_FINAL_SOURCES = {"llm", "llm_other", "llm_manual"}
MAP_MESSAGE_TYPES = {"complaint", "sarcasm", "request"}
MAP_SKIP_NAMES = {"красноярский край", "улица не указана", "не указана", "разное"}
REGION_CAPITALS = {
    "алтайский край": "Барнаул",
    "амурская область": "Благовещенск",
    "архангельская область": "Архангельск",
    "астраханская область": "Астрахань",
    "белгородская область": "Белгород",
    "брянская область": "Брянск",
    "владимирская область": "Владимир",
    "волгоградская область": "Волгоград",
    "вологодская область": "Вологда",
    "воронежская область": "Воронеж",
    "донецкая народная республика": "Донецк",
    "еврейская автономная область": "Биробиджан",
    "забайкальский край": "Чита",
    "запорожская область": "Мелитополь",
    "ивановская область": "Иваново",
    "иркутская область": "Иркутск",
    "кабардино-балкарская республика": "Нальчик",
    "калининградская область": "Калининград",
    "калужская область": "Калуга",
    "камчатский край": "Петропавловск-Камчатский",
    "карачаево-черкесская республика": "Черкесск",
    "кемеровская область": "Кемерово",
    "кемеровская область кузбасс": "Кемерово",
    "кировская область": "Киров",
    "костромская область": "Кострома",
    "краснодарский край": "Краснодар",
    "красноярский край": "Красноярск",
    "курганская область": "Курган",
    "курская область": "Курск",
    "ленинградская область": "Санкт-Петербург",
    "липецкая область": "Липецк",
    "луганская народная республика": "Луганск",
    "магаданская область": "Магадан",
    "москва": "Москва",
    "московская область": "Москва",
    "мурманская область": "Мурманск",
    "ненецкий автономный округ": "Нарьян-Мар",
    "нижегородская область": "Нижний Новгород",
    "новгородская область": "Великий Новгород",
    "новосибирская область": "Новосибирск",
    "омская область": "Омск",
    "оренбургская область": "Оренбург",
    "орловская область": "Орел",
    "пензенская область": "Пенза",
    "пермский край": "Пермь",
    "приморский край": "Владивосток",
    "псковская область": "Псков",
    "республика адыгея": "Майкоп",
    "республика алтай": "Горно-Алтайск",
    "республика башкортостан": "Уфа",
    "республика бурятия": "Улан-Удэ",
    "республика дагестан": "Махачкала",
    "республика ингушетия": "Магас",
    "республика калмыкия": "Элиста",
    "республика карелия": "Петрозаводск",
    "республика коми": "Сыктывкар",
    "республика крым": "Симферополь",
    "республика марий эл": "Йошкар-Ола",
    "республика мордовия": "Саранск",
    "республика саха якутия": "Якутск",
    "республика северная осетия алания": "Владикавказ",
    "республика татарстан": "Казань",
    "республика тыва": "Кызыл",
    "республика хакасия": "Абакан",
    "ростовская область": "Ростов-на-Дону",
    "рязанская область": "Рязань",
    "самарская область": "Самара",
    "санкт-петербург": "Санкт-Петербург",
    "саратовская область": "Саратов",
    "сахалинская область": "Южно-Сахалинск",
    "свердловская область": "Екатеринбург",
    "севастополь": "Севастополь",
    "смоленская область": "Смоленск",
    "ставропольский край": "Ставрополь",
    "тамбовская область": "Тамбов",
    "тверская область": "Тверь",
    "томская область": "Томск",
    "тульская область": "Тула",
    "тюменская область": "Тюмень",
    "удмуртская республика": "Ижевск",
    "ульяновская область": "Ульяновск",
    "хабаровский край": "Хабаровск",
    "ханты-мансийский автономный округ": "Ханты-Мансийск",
    "ханты-мансийский автономный округ югра": "Ханты-Мансийск",
    "херсонская область": "Геническ",
    "челябинская область": "Челябинск",
    "чеченская республика": "Грозный",
    "чувашская республика": "Чебоксары",
    "чукотский автономный округ": "Анадырь",
    "ямало-ненецкий автономный округ": "Салехард",
    "ярославская область": "Ярославль",
}
LOCATION_FIELDS = (
    "country",
    "region",
    "municipality",
    "district",
    "locality_type",
    "locality",
    "street_type",
    "street",
    "house",
    "building",
    "object",
)
LOCATION_SYSTEM_PROMPT = """Ты извлекаешь ТОЛЬКО явно указанную адресную иерархию из комментария.

Ничего не придумывай, не достраивай регион по знаниям, не исправляй адрес за пользователя.
Если часть адреса не написана прямо в комментарии, ставь null.
Контекст источника можно использовать только для недостающих верхнеуровневых частей
(country/region/municipality/district), если комментарий НЕ указывает другой регион
или муниципалитет явно. В notes напиши, какие поля взяты из контекста источника.
Если написано "город Ейск", это locality_type="город", locality="Ейск", region=null.
Если написано "Шарыповский район, деревня Тутуево, улица Мира", заполни район, населенный пункт и улицу.

Верни только JSON без markdown:
{
  "country": null,
  "region": null,
  "municipality": null,
  "district": null,
  "locality_type": null,
  "locality": null,
  "street_type": null,
  "street": null,
  "house": null,
  "building": null,
  "object": null,
  "raw_mentions": [],
  "certainty": "none",
  "notes": []
}

certainty:
- "none": адреса/места нет;
- "partial": есть только город/район/объект без улицы/дома;
- "specific": есть достаточно конкретный адрес, например населенный пункт + улица или улица + дом.
"""

try:
    import certifi

    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL = ssl.create_default_context()


@dataclass(frozen=True)
class DebugGeoPoint:
    lat: float
    lon: float
    region: str
    municipality: str
    locality: str
    district: str
    source: str
    precision: str = ""
    provider_query: str = ""
    provider_name: str = ""
    provider_description: str = ""
    provider_kind: str = ""
    provider_text: str = ""


def _value(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return _value(value)


def _dump_json(value: Any) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, indent=2, default=str)


def _print_step(title: str, value: Any | None = None) -> None:
    print(f"\n=== {title} ===")
    if value is not None:
        if isinstance(value, str):
            print(value)
        else:
            print(_dump_json(value))


def _clip(text: str, limit: int = 1200) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n... <trimmed {len(text) - limit} chars>"


async def _call_llm(
    comment: str,
    *,
    model: str | None,
    temperature: float | None,
    top_p: float | None,
    top_k: int | None,
    repeat_penalty: float | None,
    system_prompt_template: str | None,
) -> tuple[Any, str, dict[str, Any]]:
    """Call the same LLM prompt/parser as CommentAnalysisService, keeping raw text."""

    model_name = model or get_default_llm_model()
    prompt_repo = FilePromptRepository()
    system_prompt = (
        prompt_repo.load(system_prompt_template)
        if system_prompt_template
        else analysis_prompt.SYSTEM
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": analysis_prompt.get_analyze_prompt(comment)},
        {"role": "assistant", "content": prompt_repo.load("analysis/assistant_prefix.md")},
    ]
    client = create_llm_client(
        model=model_name,
        num_predict=settings.OLLAMA_NUM_PREDICT_ANALYTICS,
        usage_context="comment_location_debug",
        temperature=0.1 if temperature is None else temperature,
        top_p=1.0 if top_p is None else top_p,
        top_k=20 if top_k is None else top_k,
        repeat_penalty=1.02 if repeat_penalty is None else repeat_penalty,
        think=False,
    )
    meta = {
        "provider": settings.LLM_PROVIDER,
        "model": model_name,
        "num_predict": settings.OLLAMA_NUM_PREDICT_ANALYTICS,
        "temperature": 0.1 if temperature is None else temperature,
        "top_p": 1.0 if top_p is None else top_p,
        "top_k": 20 if top_k is None else top_k,
        "repeat_penalty": 1.02 if repeat_penalty is None else repeat_penalty,
        "system_prompt_template": system_prompt_template or "<analysis_prompt.SYSTEM>",
    }
    try:
        started = time.perf_counter()
        raw = await asyncio.to_thread(client.generate, messages)
        meta["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        parsed = CommentAnalysisParser().parse(raw)
        return parsed, raw, meta
    finally:
        client.close()


def _source_context_from_args(args: argparse.Namespace) -> dict[str, str]:
    pairs = {
        "source_name": args.source_name,
        "country": args.source_country,
        "region": args.source_region,
        "municipality": args.source_municipality,
        "district": args.source_district,
        "locality": args.source_locality,
    }
    return {
        key: str(value).strip()
        for key, value in pairs.items()
        if str(value or "").strip()
    }


def _source_context_text(source_context: dict[str, str]) -> str:
    if not source_context:
        return "Контекст источника: не задан."
    labels = {
        "source_name": "название источника",
        "country": "страна источника",
        "region": "регион источника",
        "municipality": "муниципалитет источника",
        "district": "район/округ источника",
        "locality": "населенный пункт источника",
    }
    lines = ["Контекст источника комментария:"]
    for key, label in labels.items():
        value = source_context.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    lines.append(
        "Используй этот контекст только как default для недостающих верхних уровней адреса."
    )
    return "\n".join(lines)


async def _call_location_llm(
    comment: str,
    *,
    source_context: dict[str, str],
    model: str | None,
    temperature: float | None,
    top_p: float | None,
    top_k: int | None,
    repeat_penalty: float | None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Extract explicit address hierarchy with a strict no-invention prompt."""

    model_name = model or get_default_llm_model()
    source_context_text = _source_context_text(source_context)
    messages = [
        {"role": "system", "content": LOCATION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Извлеки адресную иерархию из комментария. "
                "Не добавляй ничего, чего нет в тексте или в контексте источника.\n\n"
                f"{source_context_text}\n\n"
                f"Комментарий: {comment}"
            ),
        },
    ]
    client = create_llm_client(
        model=model_name,
        num_predict=450,
        usage_context="comment_location_hierarchy_debug",
        temperature=0.0 if temperature is None else temperature,
        top_p=1.0 if top_p is None else top_p,
        top_k=20 if top_k is None else top_k,
        repeat_penalty=1.02 if repeat_penalty is None else repeat_penalty,
        think=False,
    )
    meta = {
        "provider": settings.LLM_PROVIDER,
        "model": model_name,
        "num_predict": 450,
        "temperature": 0.0 if temperature is None else temperature,
        "top_p": 1.0 if top_p is None else top_p,
        "top_k": 20 if top_k is None else top_k,
        "repeat_penalty": 1.02 if repeat_penalty is None else repeat_penalty,
        "prompt": "LOCATION_SYSTEM_PROMPT in tools/debug_comment_location.py",
        "source_context": source_context,
    }
    try:
        started = time.perf_counter()
        raw = await asyncio.to_thread(client.generate, messages)
        meta["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        parsed = json.loads(extract_json_object(raw))
        return _normalize_location_payload(parsed), raw, meta
    finally:
        client.close()


def _normalize_location_payload(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    normalized: dict[str, Any] = {}
    for key in LOCATION_FIELDS:
        value = data.get(key)
        if value is None:
            normalized[key] = None
            continue
        text = str(value).strip()
        normalized[key] = text or None
    raw_mentions = data.get("raw_mentions")
    normalized["raw_mentions"] = [
        str(item).strip()
        for item in (raw_mentions if isinstance(raw_mentions, list) else [])
        if str(item).strip()
    ]
    certainty = str(data.get("certainty") or "").strip().lower()
    normalized["certainty"] = certainty if certainty in {"none", "partial", "specific"} else "none"
    notes = data.get("notes")
    normalized["notes"] = [
        str(item).strip()
        for item in (notes if isinstance(notes, list) else [])
        if str(item).strip()
    ]
    return normalized


def _apply_source_context_to_location(
    location: dict[str, Any],
    source_context: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    """Fill only missing address parts from the source context."""

    merged = dict(location)
    applied: list[str] = []
    for location_key, source_key in (("country", "country"), ("region", "region")):
        source_value = source_context.get(source_key, "").strip()
        if source_value and not str(merged.get(location_key) or "").strip():
            merged[location_key] = source_value
            applied.append(location_key)

    has_municipal_level = bool(
        str(merged.get("municipality") or "").strip()
        or str(merged.get("district") or "").strip()
    )
    if not has_municipal_level:
        for location_key, source_key in (("municipality", "municipality"), ("district", "district")):
            source_value = source_context.get(source_key, "").strip()
            if source_value:
                merged[location_key] = source_value
                applied.append(location_key)
                break

    source_locality = source_context.get("locality", "").strip()
    if source_locality and not str(merged.get("locality") or "").strip():
        merged["locality"] = source_locality
        applied.append("locality")
    if applied:
        notes = list(merged.get("notes") or [])
        notes.append(f"source_context_applied: {', '.join(applied)}")
        merged["notes"] = notes
    return merged, applied


def _normalize_region_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace("ё", "е")
    for char in (".", ",", "(", ")", "—", "-", "–"):
        text = text.replace(char, " ")
    return " ".join(text.split())


def _region_capital(region: Any) -> str:
    return REGION_CAPITALS.get(_normalize_region_key(region), "")


def _has_location_part(location: dict[str, Any], *keys: str) -> bool:
    return any(str(location.get(key) or "").strip() for key in keys)


def _location_type_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("ё", "е")


def _move_city_detail_locality_to_district(location: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Move city-level details from locality to district before capital fallback.

    LLM sometimes parses "жилой район Николаевка" as
    locality_type="район", locality="Николаевка". For a regional source this is
    usually not a separate settlement, but a city detail that should be queried
    inside the regional capital.
    """

    merged = dict(location)
    locality = str(merged.get("locality") or "").strip()
    locality_type = str(merged.get("locality_type") or "").strip()
    if not locality:
        return merged, ""
    if not _region_capital(merged.get("region")):
        return merged, ""

    city_detail_types = {
        "район",
        "жилой район",
        "микрорайон",
        "мкр",
        "жилой комплекс",
        "жк",
        "квартал",
    }
    if _location_type_key(locality_type) not in city_detail_types:
        return merged, ""

    city_detail = _join_location_part(locality_type, locality)
    existing_district = str(merged.get("district") or "").strip()
    if existing_district:
        if city_detail.lower() not in existing_district.lower():
            merged["district"] = f"{existing_district}, {city_detail}"
    else:
        merged["district"] = city_detail
    merged["locality_type"] = None
    merged["locality"] = None
    notes = list(merged.get("notes") or [])
    notes.append(f"city_detail_locality_rewrite: {city_detail}")
    merged["notes"] = notes
    return merged, city_detail


def _district_looks_like_city_detail(location: dict[str, Any]) -> bool:
    district = str(location.get("district") or "").strip().lower().replace("ё", "е")
    if not district:
        return False
    city_detail_markers = (
        "жилой район",
        "микрорайон",
        "мкр",
        "жилой комплекс",
        "жк",
        "квартал",
        "поселок",
        "посёлок",
    )
    municipal_markers = (
        "муниципальный",
        "городской округ",
        "район",
    )
    if any(marker in district for marker in city_detail_markers):
        return True
    if district.startswith("район "):
        return True
    return not any(marker in district for marker in municipal_markers)


def _strip_city_detail_type(value: Any) -> str:
    text = str(value or "").strip()
    low = text.lower().replace("ё", "е")
    prefixes = (
        "жилой район",
        "район",
        "микрорайон",
        "мкр",
        "жилой комплекс",
        "жк",
        "квартал",
    )
    for prefix in prefixes:
        if low == prefix:
            return ""
        if low.startswith(prefix + " "):
            return text[len(prefix):].strip(" ,.-")
    return text


def _candidate_detail_name(candidate: dict[str, str]) -> str:
    value = str(candidate.get("value") or "").strip()
    parts = [part.strip() for part in value.split(",") if part.strip()]
    for part in reversed(parts):
        low = _norm_match_text(part)
        if any(marker in low for marker in ("район", "микрорайон", "мкр")):
            return _strip_city_detail_type(part)
    if parts:
        return _strip_city_detail_type(parts[-1])
    return _strip_city_detail_type(value)


def _norm_match_text(value: Any) -> str:
    text = str(value or "").lower().replace("ё", "е")
    for char in "\"'«».,;:()[]{}!?—–-/":
        text = text.replace(char, " ")
    return " ".join(text.split())


def _important_tokens(value: Any) -> set[str]:
    stop_words = {
        "г",
        "город",
        "край",
        "область",
        "республика",
        "россия",
        "район",
        "микрорайон",
        "мкр",
        "парк",
        "сквер",
        "территория",
        "красноярский",
        "красноярск",
    }
    return {
        token
        for token in _norm_match_text(value).split()
        if len(token) >= 4 and token not in stop_words
    }


def _apply_region_capital_fallback(location: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Use the regional capital when source region is known but locality is absent.

    This is intentionally conservative: a lone municipal district such as
    "Енисейский район" should stay a territory-level query, while "улица Мира"
    inside a Krasnoyarsk-focused source can be tested as
    "Красноярский край, Красноярск, улица Мира".
    """

    merged = dict(location)
    if _has_location_part(merged, "locality"):
        return merged, ""

    capital = _region_capital(merged.get("region"))
    if not capital:
        return merged, ""

    has_street_level = _has_location_part(merged, "street", "house", "building", "object")
    has_city_detail = _district_looks_like_city_detail(merged)
    if not (has_street_level or has_city_detail):
        return merged, ""

    merged["locality_type"] = merged.get("locality_type") or "город"
    merged["locality"] = capital
    notes = list(merged.get("notes") or [])
    notes.append(f"region_capital_fallback_applied: {capital}")
    merged["notes"] = notes
    return merged, capital


def _join_location_part(type_value: str | None, name_value: str | None) -> str:
    type_text = (type_value or "").strip()
    name_text = (name_value or "").strip()
    if type_text and name_text:
        low_name = name_text.lower()
        low_type = type_text.lower()
        if low_name.startswith(low_type + " ") or low_name.startswith(low_type + "."):
            return name_text
        return f"{type_text} {name_text}"
    return name_text or type_text


def _object_for_query(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    generic = {
        "школа",
        "детский сад",
        "детсад",
        "садик",
        "больница",
        "поликлиника",
        "дорога",
        "мост",
        "остановка",
    }
    if text.lower() in generic:
        return ""
    return text


def _compact_location_parts(parts: list[Any]) -> str:
    compact: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = str(part or "").strip(" ,;")
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        compact.append(text)
    return ", ".join(compact)


def _build_location_query(location: dict[str, Any]) -> str:
    """Build geocoder query from larger to smaller explicit LLM-extracted parts."""

    locality_part = _join_location_part(location.get("locality_type"), location.get("locality"))
    district_part = location.get("district")
    street_part = _join_location_part(location.get("street_type"), location.get("street"))
    if locality_part and _district_looks_like_city_detail(location):
        parts = [
            location.get("country"),
            location.get("region"),
            location.get("municipality"),
            locality_part,
            district_part,
            street_part,
            location.get("house"),
            location.get("building"),
            _object_for_query(location.get("object")),
        ]
    else:
        parts = [
            location.get("country"),
            location.get("region"),
            location.get("municipality"),
            district_part,
            locality_part,
            street_part,
            location.get("house"),
            location.get("building"),
            _object_for_query(location.get("object")),
        ]
    return _compact_location_parts(parts)


def _build_city_detail_query_variants(location: dict[str, Any]) -> list[str]:
    locality = str(location.get("locality") or "").strip()
    district = str(location.get("district") or "").strip()
    if not locality or not district or not _district_looks_like_city_detail(location):
        return []

    detail_name = _strip_city_detail_type(district)
    if not detail_name:
        return []

    street_part = _join_location_part(location.get("street_type"), location.get("street"))
    tail = [
        street_part,
        location.get("house"),
        location.get("building"),
        _object_for_query(location.get("object")),
    ]
    variants = [
        _compact_location_parts([
            location.get("country"),
            location.get("region"),
            location.get("municipality"),
            locality,
            detail_name,
            *tail,
        ]),
        _compact_location_parts([
            locality,
            detail_name,
            *tail,
        ]),
        _compact_location_parts([
            location.get("country"),
            location.get("region"),
            locality,
            district,
            *tail,
        ]),
        _compact_location_parts([
            location.get("country"),
            location.get("region"),
            locality,
            f"микрорайон {detail_name}",
            *tail,
        ]),
        _compact_location_parts([
            locality,
            f"микрорайон {detail_name}",
            *tail,
        ]),
        _compact_location_parts([
            location.get("country"),
            location.get("region"),
            locality,
            f"мкр {detail_name}",
            *tail,
        ]),
        _compact_location_parts([
            locality,
            f"мкр {detail_name}",
            *tail,
        ]),
    ]
    result: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        key = variant.lower()
        if variant and key not in seen:
            seen.add(key)
            result.append(variant)
    return result


def _apply_production_normalization(payload: Any, comment: str) -> SimpleNamespace:
    analysis = SimpleNamespace(
        sentiment=None,
        relevance=None,
        confidence=None,
        summary=None,
        topics=[],
        model_version=None,
        analyzed_at=None,
        author_type=None,
        message_type=None,
        classification_source=None,
        is_official_response=False,
        hierarchy=None,
        entities=None,
    )
    apply_llm_analysis(
        analysis,
        payload=payload,
        generated_at=datetime.now(timezone.utc),
        source_text=comment,
    )
    return analysis


def _map_gate_debug(analysis: SimpleNamespace) -> dict[str, Any]:
    relevance = _value(getattr(analysis, "relevance", ""))
    source = str(getattr(analysis, "classification_source", "") or "")
    message_type = str(getattr(analysis, "message_type", "") or "")
    hierarchy = getattr(analysis, "hierarchy", None) or {}
    case_name = str(hierarchy.get("case") or "").strip()
    reasons: list[str] = []
    if relevance != RelevanceEnum.relevant.value:
        reasons.append("ca.relevance != 'relevant'")
    if source not in MAP_FINAL_SOURCES:
        reasons.append("classification_source not in ('llm','llm_other','llm_manual')")
    if not case_name:
        reasons.append("hierarchy.case is empty")
    if message_type not in MAP_MESSAGE_TYPES:
        reasons.append("message_type is not complaint/sarcasm/request")
    if case_name.lower() in MAP_SKIP_NAMES:
        reasons.append("case is in map skip list")
    if case_name and not is_valid_case_title(case_name):
        reasons.append("case failed is_valid_case_title")
    return {
        "would_enter_map_sql": (
            relevance == RelevanceEnum.relevant.value
            and source in MAP_FINAL_SOURCES
            and bool(case_name)
        ),
        "would_be_geocoded_by_map": not reasons,
        "reasons_if_no": reasons,
        "production_case": case_name,
        "case_location_key": case_location_key(case_name) if case_name else "",
        "display_title_before_geocode": address_display_title(case_name, None) if case_name else "",
    }


def _candidate_list(
    payload: Any,
    analysis: SimpleNamespace,
    *,
    location_payload: dict[str, Any] | None,
    include_entities: bool,
) -> list[dict[str, str]]:
    hierarchy = getattr(analysis, "hierarchy", None) or {}
    raw_hierarchy = payload.hierarchy.model_dump()
    entities = payload.entities.model_dump()
    candidates: list[dict[str, str]] = []

    if location_payload:
        expected_region = str(location_payload.get("region") or "").strip()
        expected_locality = str(location_payload.get("locality") or "").strip()
        location_query = _build_location_query(location_payload)
        if location_query:
            candidates.append({
                "kind": "llm_address_hierarchy",
                "value": location_query,
                "expected_region": expected_region,
                "expected_locality": expected_locality,
                "note": (
                    "Экспериментальный кандидат: отдельный LLM-вызов извлёк "
                    "явную адресную иерархию, строка собрана от большего к меньшему."
                ),
            })
        for variant in _build_city_detail_query_variants(location_payload):
            if variant not in {item["value"] for item in candidates}:
                candidates.append({
                    "kind": "llm_address_hierarchy:city_detail_variant",
                    "value": variant,
                    "expected_region": expected_region,
                    "expected_locality": expected_locality,
                    "note": (
                        "Диагностический вариант для городского района/микрорайона: "
                        "часть типа 'район' смягчена или убрана, потому что геокодеры "
                        "часто не понимают неофициальные жилые районы как адресный уровень."
                    ),
                })

    production_case = str(hierarchy.get("case") or "").strip()
    if production_case and production_case not in {item["value"] for item in candidates}:
        candidates.append({
            "kind": "production:hierarchy.case",
            "value": production_case,
            "note": "Именно это имя карты берут из comment_analysis.hierarchy.case.",
        })

    raw_case = str(raw_hierarchy.get("case") or "").strip()
    if raw_case and raw_case != production_case:
        candidates.append({
            "kind": "debug:raw_llm_hierarchy.case",
            "value": raw_case,
            "note": "Сырой case до normalize_hierarchy_values; карта его напрямую не берёт.",
        })

    if include_entities:
        for key in ("address", "institution"):
            value = str(entities.get(key) or "").strip()
            if value and value not in {item["value"] for item in candidates}:
                candidates.append({
                    "kind": f"debug:entities.{key}",
                    "value": value,
                    "note": "Диагностический fallback: текущая карта это поле напрямую не геокодит.",
                })
    return candidates


def _load_provider_json(
    req: urllib.request.Request,
    *,
    timeout: int,
    provider: str,
    query: str,
) -> Any:
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
        return json.load(resp)


def _admin_hierarchy_from_yandex(meta: dict[str, Any]) -> tuple[str, str, str]:
    try:
        comps = meta["Address"]["Components"]
    except (KeyError, TypeError):
        return "", "", ""
    by_kind = {
        str(c.get("kind") or ""): str(c.get("name") or "")
        for c in comps
        if c.get("kind") and c.get("name")
    }
    region = by_kind.get("province") or ""
    municipality = by_kind.get("area") or by_kind.get("locality") or ""
    locality = by_kind.get("locality") or by_kind.get("district") or ""
    return region, municipality, locality


def _yandex_direct(query: str, timeout: int) -> DebugGeoPoint | None:
    key = getattr(settings, "YANDEX_GEOCODER_KEY", "") or ""
    if not key:
        return None
    params = urllib.parse.urlencode({
        "apikey": key,
        "geocode": query,
        "format": "json",
        "results": 1,
        "lang": "ru_RU",
    })
    req = urllib.request.Request("https://geocode-maps.yandex.ru/1.x/?" + params)
    data = _load_provider_json(req, timeout=timeout, provider="yandex", query=query)
    feats = data["response"]["GeoObjectCollection"]["featureMember"]
    if not feats:
        return None
    geo_object = feats[0]["GeoObject"]
    lon, lat = geo_object["Point"]["pos"].split()
    meta = geo_object["metaDataProperty"]["GeocoderMetaData"]
    region, municipality, locality = _admin_hierarchy_from_yandex(meta)
    district = municipality or locality or region or geo_object.get("name", "")
    return DebugGeoPoint(
        lat=float(lat),
        lon=float(lon),
        region=region,
        municipality=municipality,
        locality=locality,
        district=district,
        source="yandex",
        precision=str(meta.get("precision") or ""),
        provider_query=query,
        provider_name=str(geo_object.get("name") or ""),
        provider_description=str(geo_object.get("description") or ""),
        provider_kind=str(meta.get("kind") or ""),
        provider_text=str(meta.get("text") or ""),
    )


def _dadata_direct(query: str, timeout: int) -> DebugGeoPoint | None:
    token = getattr(settings, "DADATA_TOKEN", "") or ""
    secret = getattr(settings, "DADATA_SECRET", "") or ""
    if not (token and secret):
        return None
    body = json.dumps([query], ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://cleaner.dadata.ru/api/v1/clean/address",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Token " + token,
            "X-Secret": secret,
        },
    )
    data = _load_provider_json(req, timeout=timeout, provider="dadata", query=query)
    if not data:
        return None
    row = data[0]
    lat, lon = row.get("geo_lat"), row.get("geo_lon")
    if not lat or not lon:
        return None
    region = row.get("region_with_type") or row.get("region") or ""
    municipality = (
        row.get("area_with_type")
        or row.get("city_district_with_type")
        or row.get("city_with_type")
        or ""
    )
    locality = row.get("settlement_with_type") or row.get("city_with_type") or ""
    district = municipality or locality or region
    return DebugGeoPoint(
        lat=float(lat),
        lon=float(lon),
        region=str(region),
        municipality=str(municipality),
        locality=str(locality),
        district=str(district),
        source="dadata",
        precision=str(row.get("qc_geo") or ""),
        provider_query=query,
        provider_name=str(row.get("result") or ""),
        provider_description=str(row.get("unrestricted_value") or ""),
        provider_kind=str(row.get("qc_geo") or ""),
        provider_text=str(row.get("source") or query),
    )


def _direct_geocode(query: str, *, timeout: int) -> DebugGeoPoint | None:
    low_precision_point: DebugGeoPoint | None = None
    for provider in (_yandex_direct, _dadata_direct):
        try:
            point = provider(query, timeout)
        except Exception as exc:  # noqa: BLE001
            print(f"[geocoder:{provider.__name__}] failed for {query!r}: {exc}", file=sys.stderr)
            continue
        if point:
            if point.source == "yandex" and point.precision == "other":
                low_precision_point = point
                continue
            return point
    return low_precision_point


def _candidate_allows_area_centroid(candidate: dict[str, str], geo: dict[str, Any]) -> bool:
    if candidate.get("kind") not in {
        "llm_address_hierarchy",
        "llm_address_hierarchy:city_detail_variant",
    }:
        return False
    value = str(candidate.get("value") or "").lower().replace("ё", "е")
    if not any(marker in value for marker in ("район", "микрорайон", "мкр")):
        return False
    if not _geo_matches_expected_place(candidate, geo):
        return False

    provider_tokens = _important_tokens(
        " ".join([
            str(geo.get("provider_name") or ""),
            str(geo.get("provider_text") or ""),
            str(geo.get("provider_description") or ""),
        ])
    )
    detail_tokens = _important_tokens(_candidate_detail_name(candidate))
    expected_place_tokens = (
        _important_tokens(candidate.get("expected_region"))
        | _important_tokens(candidate.get("expected_locality"))
    )
    detail_tokens -= expected_place_tokens
    return bool(detail_tokens) and detail_tokens.issubset(provider_tokens)


def _candidate_allows_locality_centroid(candidate: dict[str, str], geo: dict[str, Any]) -> bool:
    """Accept a Yandex locality centroid when the locality name itself is confirmed.

    Yandex marks cities/villages as precision=other, but for map purposes a matched
    locality is a useful point. Keep this stricter than generic precision=other:
    the provider must return a locality and its text must contain the requested
    locality tokens. This rejects multi-place strings like "Выкса, Кулебаки" when
    Yandex silently chooses only one of them.
    """

    if _norm_match_text(geo.get("provider_kind")) != "locality":
        return False

    expected_region = _norm_match_text(candidate.get("expected_region"))
    if expected_region and not _geo_matches_expected_place(candidate, geo):
        return False

    provider_tokens = _important_tokens(
        " ".join([
            str(geo.get("provider_name") or ""),
            str(geo.get("provider_text") or ""),
            str(geo.get("provider_description") or ""),
            str(geo.get("locality") or ""),
        ])
    )
    detail_tokens = _important_tokens(_candidate_detail_name(candidate))
    expected_place_tokens = (
        _important_tokens(candidate.get("expected_region"))
        | _important_tokens(candidate.get("expected_locality"))
    )
    detail_tokens -= expected_place_tokens
    return bool(detail_tokens) and detail_tokens.issubset(provider_tokens)


def _geo_matches_expected_place(candidate: dict[str, str], geo: dict[str, Any]) -> bool:
    provider_blob = _norm_match_text(
        " ".join([
            str(geo.get("provider_text") or ""),
            str(geo.get("provider_name") or ""),
            str(geo.get("provider_description") or ""),
            str(geo.get("locality") or ""),
            str(geo.get("municipality") or ""),
            str(geo.get("region") or ""),
        ])
    )

    expected_locality = _norm_match_text(candidate.get("expected_locality"))
    if expected_locality:
        return expected_locality in provider_blob

    expected_region = _norm_match_text(candidate.get("expected_region"))
    if expected_region:
        return expected_region in provider_blob

    return False


def _candidate_allows_named_object_area(candidate: dict[str, str], geo: dict[str, Any]) -> bool:
    if candidate.get("kind") != "llm_address_hierarchy":
        return False

    value = _norm_match_text(candidate.get("value"))
    object_markers = ("парк", "сквер", "набережная", "бульвар", "площадь", "сад")
    if not any(marker in value for marker in object_markers):
        return False

    provider_kind = _norm_match_text(geo.get("provider_kind"))
    if provider_kind not in {"vegetation", "district", "hydro", "locality"}:
        return False

    if not _geo_matches_expected_place(candidate, geo):
        return False

    candidate_tokens = _important_tokens(candidate.get("value"))
    provider_tokens = _important_tokens(
        " ".join([
            str(geo.get("provider_name") or ""),
            str(geo.get("provider_text") or ""),
        ])
    )
    return bool(candidate_tokens) and candidate_tokens.issubset(provider_tokens)


def _geocode_candidate(candidate: dict[str, str], *, timeout: int) -> dict[str, Any]:
    name = candidate["value"].strip()
    result: dict[str, Any] = {
        **candidate,
        "provider_query": name,
        "is_valid_case_title": is_valid_case_title(name),
        "case_location_key": case_location_key(name),
    }
    if not name:
        result["status"] = "skip_empty"
        return result
    if name.lower() in MAP_SKIP_NAMES:
        result["status"] = "skip_map_stop_name"
        return result
    if candidate["kind"].startswith("production:") and not result["is_valid_case_title"]:
        result["status"] = "skip_invalid_production_case"
        return result

    started = time.perf_counter()
    point = _direct_geocode(name, timeout=timeout)
    result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    if point is None:
        result["status"] = "miss"
        return result
    geo = asdict(point)
    if geo.get("source") == "yandex" and geo.get("precision") == "other":
        if _candidate_allows_named_object_area(candidate, geo):
            result.update(
                {
                    "status": "poi_area",
                    "note": (
                        str(result.get("note") or "")
                        + " Accepted as a named object area: provider matched the object name inside the expected city."
                    ).strip(),
                    "geo": geo,
                    "display_title": address_display_title(name, geo),
                    "canonical_title": address_canonical_title(name, geo),
                }
            )
            return result
        if _candidate_allows_area_centroid(candidate, geo):
            result.update(
                {
                    "status": "area_centroid",
                    "note": (
                        str(result.get("note") or "")
                        + " Accepted as an area centroid: city-detail candidate resolved inside the expected city."
                    ).strip(),
                    "geo": geo,
                    "display_title": address_display_title(name, geo),
                    "canonical_title": address_canonical_title(name, geo),
                }
            )
            return result
        if _candidate_allows_locality_centroid(candidate, geo):
            result.update(
                {
                    "status": "locality_centroid",
                    "note": (
                        str(result.get("note") or "")
                        + " Accepted as a locality centroid: provider matched the requested locality name."
                    ).strip(),
                    "geo": geo,
                    "display_title": address_display_title(name, geo),
                    "canonical_title": address_canonical_title(name, geo),
                }
            )
            return result
        result.update(
            {
                "status": "low_precision",
                "reject_reason": "yandex precision=other is too coarse for final map coordinate",
                "geo": geo,
                "display_title": address_display_title(name, geo),
                "canonical_title": address_canonical_title(name, geo),
            }
        )
        return result
    result.update(
        {
            "status": "hit",
            "geo": geo,
            "display_title": address_display_title(name, geo),
            "canonical_title": address_canonical_title(name, geo),
        }
    )
    return result


async def run(args: argparse.Namespace) -> int:
    comment = args.comment.strip()
    if not comment:
        print("Комментарий пустой.", file=sys.stderr)
        return 2

    source_context = _source_context_from_args(args)
    debug: dict[str, Any] = {
        "comment": comment,
        "settings": {
            "llm_provider": settings.LLM_PROVIDER,
            "default_model": get_default_llm_model(),
            "yandex_key_configured": bool(getattr(settings, "YANDEX_GEOCODER_KEY", "") or ""),
            "dadata_token_configured": bool(getattr(settings, "DADATA_TOKEN", "") or ""),
            "dadata_secret_configured": bool(getattr(settings, "DADATA_SECRET", "") or ""),
            "geo_timeout_seconds": args.geo_timeout,
            "geocoder_mode": "tool_direct_yandex_then_dadata_no_forced_region",
            "geo_cache_path": str(settings.geo_cache_path_abs),
            "source_context": source_context,
            "known_region_capital": _region_capital(source_context.get("region")),
        },
    }

    try:
        payload, raw_response, llm_meta = await _call_llm(
            comment,
            model=args.model,
            temperature=args.temperature,
            top_p=args.top_p,
            top_k=args.top_k,
            repeat_penalty=args.repeat_penalty,
            system_prompt_template=args.system_prompt_template,
        )
    except (LLMError, ValidationError, json.JSONDecodeError, ValueError) as exc:
        debug["llm_error"] = repr(exc)
        if args.json:
            print(_dump_json(debug))
        else:
            _print_step("Входной комментарий", comment)
            _print_step("Ошибка LLM/парсинга", repr(exc))
        return 1

    location_payload: dict[str, Any] | None = None
    location_raw_response = ""
    location_llm_meta: dict[str, Any] | None = None
    location_error = ""
    try:
        location_payload, location_raw_response, location_llm_meta = await _call_location_llm(
            comment,
            source_context=source_context,
            model=args.model,
            temperature=args.location_temperature,
            top_p=args.top_p,
            top_k=args.top_k,
            repeat_penalty=args.repeat_penalty,
        )
    except (LLMError, ValidationError, json.JSONDecodeError, ValueError) as exc:
        location_error = repr(exc)

    analysis = _apply_production_normalization(payload, comment)
    raw_payload = payload.model_dump()
    normalized = {
        "relevance": _value(analysis.relevance),
        "sentiment": _value(analysis.sentiment),
        "author_type": analysis.author_type,
        "message_type": analysis.message_type,
        "classification_source": analysis.classification_source,
        "is_official_response": analysis.is_official_response,
        "hierarchy": analysis.hierarchy,
        "entities": analysis.entities,
        "summary": analysis.summary,
        "topics": analysis.topics,
            "model_version": analysis.model_version,
    }
    map_gate = _map_gate_debug(analysis)
    effective_location_payload = None
    source_context_applied: list[str] = []
    city_detail_locality_rewrite = ""
    region_capital_fallback = ""
    if location_payload is not None:
        effective_location_payload, source_context_applied = _apply_source_context_to_location(
            location_payload,
            source_context,
        )
        effective_location_payload, city_detail_locality_rewrite = _move_city_detail_locality_to_district(
            effective_location_payload,
        )
        effective_location_payload, region_capital_fallback = _apply_region_capital_fallback(
            effective_location_payload,
        )
    location_query = _build_location_query(effective_location_payload or {})
    candidates = _candidate_list(
        payload,
        analysis,
        location_payload=effective_location_payload,
        include_entities=not args.no_entities_fallback,
    )
    geocoded = [
        _geocode_candidate(candidate, timeout=args.geo_timeout)
        for candidate in candidates
    ]
    final = next(
        (item for item in geocoded if item.get("status") in {"hit", "area_centroid", "poi_area"}),
        None,
    )

    debug.update(
        {
            "llm": {
                **llm_meta,
                "raw_response": raw_response,
                "parsed_payload": raw_payload,
            },
            "production_normalized_analysis": normalized,
            "address_hierarchy_llm": (
                {
                    **(location_llm_meta or {}),
                    "raw_response": location_raw_response,
                    "parsed_payload": location_payload,
                    "effective_payload": effective_location_payload,
                    "source_context_applied": source_context_applied,
                    "city_detail_locality_rewrite": city_detail_locality_rewrite,
                    "region_capital_fallback": region_capital_fallback,
                    "geocoder_query": location_query,
                }
                if location_payload is not None
                else {"error": location_error}
            ),
            "map_gate": map_gate,
            "geocode_candidates": geocoded,
            "final_coordinate": (
                {
                    "lat": final["geo"]["lat"],
                    "lon": final["geo"]["lon"],
                    "source": final["geo"]["source"],
                    "precision": final["geo"].get("precision", ""),
                    "status": final.get("status", ""),
                    "candidate_kind": final["kind"],
                    "candidate_value": final["value"],
                    "display_title": final.get("display_title", ""),
                }
                if final
                else None
            ),
        }
    )

    if args.json:
        if not args.show_raw:
            debug["llm"]["raw_response"] = _clip(raw_response)
            if isinstance(debug.get("address_hierarchy_llm"), dict):
                raw_location = debug["address_hierarchy_llm"].get("raw_response")
                if isinstance(raw_location, str):
                    debug["address_hierarchy_llm"]["raw_response"] = _clip(raw_location)
        print(_dump_json(debug))
    else:
        _print_step("Входной комментарий", comment)
        _print_step("Настройки", debug["settings"])
        _print_step("LLM вызов", llm_meta)
        if args.show_raw:
            _print_step("Сырой ответ LLM", raw_response)
        else:
            _print_step("Сырой ответ LLM (обрезанный)", _clip(raw_response))
        _print_step("Распарсенный payload LLM", raw_payload)
        _print_step("После production-нормализации apply_llm_analysis", normalized)
        if location_payload is not None:
            _print_step("LLM адресная иерархия", {
                **(location_llm_meta or {}),
                "parsed_payload": location_payload,
                "effective_payload": effective_location_payload,
                "source_context_applied": source_context_applied,
                "city_detail_locality_rewrite": city_detail_locality_rewrite,
                "region_capital_fallback": region_capital_fallback,
                "geocoder_query": location_query,
            })
            if args.show_raw:
                _print_step("Сырой ответ LLM адресной иерархии", location_raw_response)
            else:
                _print_step("Сырой ответ LLM адресной иерархии (обрезанный)", _clip(location_raw_response))
        else:
            _print_step("Ошибка LLM адресной иерархии", location_error)
        _print_step("Проверки попадания в карту", map_gate)
        _print_step("Кандидаты и геокодинг", geocoded)
        if debug["final_coordinate"]:
            _print_step("ИТОГОВАЯ КООРДИНАТА", debug["final_coordinate"])
            print(f"{debug['final_coordinate']['lat']}, {debug['final_coordinate']['lon']}")
        else:
            _print_step("ИТОГОВАЯ КООРДИНАТА", "Не найдена.")
    return 0 if debug["final_coordinate"] else 3


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Прогнать один комментарий через LLM-классификацию и геокодинг карты."
    )
    parser.add_argument("comment", nargs="?", default="", help="Текст комментария.")
    parser.add_argument("--source-name", default="", help="Название паблика/источника комментария.")
    parser.add_argument("--source-country", default="", help="Страна источника, если известна.")
    parser.add_argument("--source-region", default="", help="Регион источника, если известен.")
    parser.add_argument("--source-municipality", default="", help="Муниципалитет источника, если известен.")
    parser.add_argument("--source-district", default="", help="Район/округ источника, если известен.")
    parser.add_argument("--source-locality", default="", help="Населенный пункт источника, если известен.")
    parser.add_argument("--model", default=None, help="Переопределить модель LLM.")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument(
        "--location-temperature",
        type=float,
        default=None,
        help="Температура отдельного LLM-вызова для адресной иерархии. По умолчанию 0.0.",
    )
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--repeat-penalty", type=float, default=None)
    parser.add_argument(
        "--system-prompt-template",
        default=None,
        help="Например: analysis/system3.md. По умолчанию используется production analysis_prompt.SYSTEM.",
    )
    parser.add_argument(
        "--geo-timeout",
        type=int,
        default=int(getattr(settings, "GEO_TIMEOUT_SECONDS", 15)),
        help="Timeout одного запроса к геокодеру.",
    )
    parser.add_argument(
        "--no-entities-fallback",
        action="store_true",
        help="Показывать только production hierarchy.case, без диагностических candidates из entities.",
    )
    parser.add_argument("--show-raw", action="store_true", help="Печатать полный сырой ответ LLM.")
    parser.add_argument("--json", action="store_true", help="Вывести весь debug как JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
