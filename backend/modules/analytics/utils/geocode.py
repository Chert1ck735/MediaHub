"""Геокодинг адресных кейсов: адрес → координаты + район.

Яндекс Geocoder — primary, DaData clean/address — fallback (ФИАС по РФ).
Синхронный — вызывать через ``asyncio.to_thread``.
"""
from __future__ import annotations

import json
import math
import logging
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass

import sentry_sdk

from backend.app.config import settings
from backend.modules.analytics.utils.geo_keys import note_rejected, note_request, take_key

logger = logging.getLogger(__name__)

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL = ssl.create_default_context()

# Тип-слова в предложном/др. падеже → именительный (геокодеры лучше берут
# «село Успенка», чем «селе Успенка»). Правим только префикс-тип, имя не трогаем.
_TYPE_FIX = (
    ("селе ", "село "), ("посёлке ", "посёлок "), ("поселке ", "поселок "),
    ("городе ", "город "), ("деревне ", "деревня "), ("станице ", "станица "),
    ("посёлок городского типа ", "пгт "),
)


def _normalize(address: str) -> str:
    a = (address or "").strip()
    low = a.lower()
    for decl, nom in _TYPE_FIX:
        if low.startswith(decl):
            return nom + a[len(decl):]
    return a


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float
    region: str          # субъект РФ / регион верхнего уровня
    municipality: str    # муниципалитет / городской округ / район
    locality: str        # населённый пункт или район города
    district: str        # legacy-поле для старого UI: municipality -> locality -> region
    source: str          # dadata | yandex
    precision: str = ""  # точность геокодера (yandex): exact/number/street/...
    provider_name: str = ""
    provider_description: str = ""
    provider_kind: str = ""
    provider_text: str = ""


def _with_region(address: str) -> str:
    return _normalize(address)


def _load_provider_json(
    req: urllib.request.Request,
    *,
    timeout: int,
    provider: str,
    address: str,
):
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
            return json.load(resp)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Geocoder provider %s failed for address %r: %s",
            provider,
            address,
            exc,
        )
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("geocoder.provider", provider)
            scope.set_context(
                "geocoder",
                {
                    "provider": provider,
                    "address": address[:200],
                    "timeout_seconds": timeout,
                },
            )
            sentry_sdk.capture_exception(exc)
        raise


def _yandex_response(address: str, timeout: int):
    """Ответ Яндекса, с переходом на следующий ключ при отказе.

    Ключи лежат на личных аккаунтах разных людей и выбывают поодиночке: у
    одного кончилась суточная норма, другой отозвали. Отказ не должен стоить
    нам запроса — пробуем следующий ключ сразу.
    """
    tried: set[str] = set()
    while True:
        key = take_key()
        if not key or key in tried:
            return None
        tried.add(key)
        query = urllib.parse.urlencode({
            "apikey": key, "geocode": _with_region(address),
            "format": "json", "results": 1, "lang": "ru_RU",
        })
        request = urllib.request.Request("https://geocode-maps.yandex.ru/1.x/?" + query)
        note_request(key)
        try:
            return _load_provider_json(request, timeout=timeout, provider="yandex", address=address)
        except urllib.error.HTTPError as exc:
            # 403 — ключ исчерпан или отозван, 429 — слишком часто. И то, и другое
            # лечится сменой ключа; остальные ошибки к ключу отношения не имеют.
            if exc.code not in (403, 429):
                raise
            note_rejected(key)


def _yandex(address: str, timeout: int) -> GeoPoint | None:
    data = _yandex_response(address, timeout)
    if data is None:
        return None
    feats = data["response"]["GeoObjectCollection"]["featureMember"]
    if not feats:
        return None
    g = feats[0]["GeoObject"]
    lon, lat = g["Point"]["pos"].split()
    meta = g["metaDataProperty"]["GeocoderMetaData"]
    region, municipality, locality = _admin_hierarchy_from_yandex(meta)
    district = municipality or locality or region or g.get("name", "")
    return GeoPoint(
        float(lat),
        float(lon),
        region,
        municipality,
        locality,
        district,
        "yandex",
        meta.get("precision", ""),
        provider_name=str(g.get("name") or ""),
        provider_description=str(g.get("description") or ""),
        provider_kind=str(meta.get("kind") or ""),
        provider_text=str(meta.get("text") or ""),
    )


def _admin_hierarchy_from_yandex(meta: dict) -> tuple[str, str, str]:
    """Достаёт регион РФ, муниципалитет и населённый пункт из компонентов Яндекса."""

    try:
        comps = meta["Address"]["Components"]
    except (KeyError, TypeError):
        return "", "", ""
    by_kind = {c["kind"]: c["name"] for c in comps if "kind" in c and "name" in c}
    region = by_kind.get("province") or ""
    municipality = by_kind.get("area") or by_kind.get("locality") or ""
    locality = by_kind.get("locality") or by_kind.get("district") or ""
    return region, municipality, locality


# «Стандартизация» — платная фича DaData; после первого 403 не долбим её зря
_dadata_clean_disabled = False


def _dadata(address: str, timeout: int) -> GeoPoint | None:
    global _dadata_clean_disabled
    token = getattr(settings, "DADATA_TOKEN", "") or ""
    secret = getattr(settings, "DADATA_SECRET", "") or ""
    if not (token and secret) or _dadata_clean_disabled:
        return None
    body = json.dumps([_with_region(address)]).encode("utf-8")
    req = urllib.request.Request(
        "https://cleaner.dadata.ru/api/v1/clean/address", data=body,
        headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "Authorization": "Token " + token, "X-Secret": secret,
        },
    )
    try:
        data = _load_provider_json(req, timeout=timeout, provider="dadata", address=address)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            _dadata_clean_disabled = True
            logger.warning("DaData clean недоступен (403) — переключаюсь на suggest")
        raise
    if not data:
        return None
    r = data[0]
    lat, lon = r.get("geo_lat"), r.get("geo_lon")
    if not lat or not lon:
        return None
    region = r.get("region_with_type") or r.get("region") or ""
    municipality = (
        r.get("area_with_type")
        or r.get("city_district_with_type")
        or r.get("city_with_type")
        or ""
    )
    locality = r.get("settlement_with_type") or r.get("city_with_type") or ""
    district = municipality or locality or region
    return GeoPoint(
        float(lat),
        float(lon),
        region,
        municipality,
        locality,
        district,
        "dadata",
        str(r.get("qc_geo", "")),
        provider_name=str(r.get("result") or ""),
        provider_description=str(r.get("unrestricted_value") or ""),
        provider_kind=str(r.get("qc_geo") or ""),
        provider_text=str(r.get("source") or address),
    )


def _dadata_suggest(address: str, timeout: int) -> GeoPoint | None:
    """Бесплатный Suggest API DaData: только токен, без подписки на «Стандартизацию»."""
    token = getattr(settings, "DADATA_TOKEN", "") or ""
    if not token:
        return None
    body = json.dumps({"query": _with_region(address), "count": 1}).encode("utf-8")
    req = urllib.request.Request(
        "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address",
        data=body,
        headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "Authorization": "Token " + token,
        },
    )
    data = _load_provider_json(req, timeout=timeout, provider="dadata_suggest", address=address)
    suggestions = (data or {}).get("suggestions") or []
    if not suggestions:
        return None
    r = suggestions[0].get("data") or {}
    lat, lon = r.get("geo_lat"), r.get("geo_lon")
    if not lat or not lon:
        return None
    region = r.get("region_with_type") or r.get("region") or ""
    municipality = (
        r.get("area_with_type")
        or r.get("city_district_with_type")
        or r.get("city_with_type")
        or ""
    )
    locality = r.get("settlement_with_type") or r.get("city_with_type") or ""
    district = municipality or locality or region
    return GeoPoint(
        float(lat),
        float(lon),
        region,
        municipality,
        locality,
        district,
        "dadata_suggest",
        str(r.get("qc_geo", "")),
        provider_name=str(suggestions[0].get("value") or ""),
        provider_description=str(suggestions[0].get("unrestricted_value") or ""),
        provider_kind=str(r.get("qc_geo") or ""),
        provider_text=str(suggestions[0].get("value") or address),
    )


# Типы регионов: DaData фильтрует по имени без типа — «Красноярский», а не
# «Красноярский край». С полным названием подсказки не находятся вовсе.
_REGION_TYPE_WORDS = ("край", "область", "автономный округ", "автономная область")


def _split_leading_region(address: str) -> tuple[str, str]:
    """«Красноярский край, Дивногорск, ул. Мира» → («Красноярский», «Дивногорск, ул. Мира»)."""
    head, _, tail = address.partition(",")
    head = head.strip()
    for word in _REGION_TYPE_WORDS:
        if head.lower().endswith(" " + word):
            return head[: -len(word) - 1].strip(), (tail.strip() or address)
    return "", address


def _dadata_suggest_scoped(address: str, timeout: int) -> GeoPoint | None:
    """Suggest, ограниченный регионом из запроса.

    Без ограничения подсказка ранжируется по популярности: «село Рыбное,
    улица Ленина» уезжает в Тамбовскую область.
    """
    token = getattr(settings, "DADATA_TOKEN", "") or ""
    if not token:
        return None
    region, query = _split_leading_region(address)
    payload: dict = {"query": query, "count": 1, "to_bound": {"value": "house"}}
    if region:
        payload["locations"] = [{"region": region}]
    req = urllib.request.Request(
        "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Token " + token,
        },
    )
    data = _load_provider_json(req, timeout=timeout, provider="dadata_suggest_scoped", address=address)
    suggestions = (data or {}).get("suggestions") or []
    if not suggestions:
        return None
    return _point_from_dadata(suggestions[0].get("data") or {}, suggestions[0], "dadata_suggest_scoped")


def _point_from_dadata(data: dict, suggestion: dict, source: str) -> GeoPoint | None:
    lat, lon = data.get("geo_lat"), data.get("geo_lon")
    if not lat or not lon:
        return None
    region = data.get("region_with_type") or data.get("region") or ""
    municipality = (
        data.get("area_with_type")
        or data.get("city_district_with_type")
        or data.get("city_with_type")
        or ""
    )
    locality = data.get("settlement_with_type") or data.get("city_with_type") or ""
    return GeoPoint(
        float(lat),
        float(lon),
        region,
        municipality,
        locality,
        municipality or locality or region,
        source,
        str(data.get("qc_geo", "")),
        provider_name=str(suggestion.get("value") or ""),
        provider_description=str(suggestion.get("unrestricted_value") or ""),
        provider_kind=str(data.get("fias_level") or ""),
        provider_text=str(suggestion.get("value") or ""),
    )


# Провайдеры, чьё согласие считаем подтверждением. Держим отдельно от боевой
# цепочки: они не заменяют основной геокодер, а голосуют за его ответ.
CONSENSUS_PROVIDERS = {
    "yandex": _yandex,
    "dadata_suggest_scoped": _dadata_suggest_scoped,
}

# Ответы ближе этого считаем указанием на одно место.
SAME_PLACE_KM = 0.3


def _distance_km(left: GeoPoint, right: GeoPoint) -> float:
    radius = 6371.0
    lat1, lon1 = math.radians(left.lat), math.radians(left.lon)
    lat2, lon2 = math.radians(right.lat), math.radians(right.lon)
    half = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * radius * math.asin(min(1.0, math.sqrt(half)))


def geocode_candidates(address: str, *, timeout: int = 15) -> list[tuple[str, GeoPoint]]:
    """Ответы всех настроенных провайдеров на один запрос."""
    if not (address or "").strip():
        return []
    found: list[tuple[str, GeoPoint]] = []
    for name, fn in CONSENSUS_PROVIDERS.items():
        try:
            point = fn(address, timeout)
        except Exception:  # noqa: BLE001 — молчание одного не роняет остальных
            continue
        if point:
            found.append((name, point))
    return found


def agreement(candidates: list[tuple[str, GeoPoint]]) -> tuple[GeoPoint | None, list[str]]:
    """Точка, за которую голосует больше провайдеров, и список согласных.

    Возвращает первого из согласных: его ответ обычно точнее, потому что
    порядок провайдеров задан по убыванию качества.
    """
    best: tuple[GeoPoint | None, list[str]] = (None, [])
    for name, point in candidates:
        agreed = [
            other_name
            for other_name, other in candidates
            if _distance_km(point, other) <= SAME_PLACE_KM
        ]
        if len(agreed) > len(best[1]):
            best = (point, agreed)
    return best


def geocode(address: str, *, timeout: int = 15) -> GeoPoint | None:
    """Геокодит адрес. По умолчанию только Яндекс; DaData — по настройке."""
    if not (address or "").strip():
        return None
    providers = (_yandex,)
    if getattr(settings, "GEO_USE_DADATA_FALLBACK", False):
        providers += (_dadata, _dadata_suggest)
    for fn in providers:
        try:
            point = fn(address, timeout)
            if point:
                return point
        except Exception:  # noqa: BLE001 — недоступность/квота одного не роняет пайплайн
            continue
    return None
