"""Реестр геокодеров для инструментов замера.

Боевая цепочка (`utils.geocode.geocode`) знает только тех провайдеров, что
включены в продакшене. Здесь собраны все кандидаты, включая те, что мы пока
только оцениваем, — чтобы `geo_bench`, `geo_eval_run` и `geo_label` брали их
из одного места и сравнивали одинаково.

Провайдер участвует, если настроен ключ; иначе возвращает None и просто не
попадает в сравнение.
"""
from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request

from backend.app.config import settings
# Замер обязан мерить боевой код, а не собственную копию: разъехавшиеся
# версии дают цифры, не соответствующие проду.
from backend.modules.analytics.utils.geocode import (
    GeoPoint,
    _dadata,
    _dadata_suggest,
    _dadata_suggest_scoped,
    _yandex,
)

try:
    import certifi

    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL = ssl.create_default_context()


def _load(request: urllib.request.Request, timeout: int):
    with urllib.request.urlopen(request, timeout=timeout, context=_SSL) as response:
        return json.load(response)


def _osm(address: str, timeout: int) -> GeoPoint | None:
    """Nominatim: бесплатно, но не чаще одного запроса в секунду."""
    query = urllib.parse.urlencode(
        {"q": address, "format": "json", "limit": 1, "addressdetails": 1, "accept-language": "ru"}
    )
    request = urllib.request.Request(
        "https://nominatim.openstreetmap.org/search?" + query,
        headers={"User-Agent": "mediahub-geo-bench/1.0"},
    )
    data = _load(request, timeout)
    if not data:
        return None
    item = data[0]
    details = item.get("address") or {}
    region = details.get("state") or ""
    municipality = details.get("county") or details.get("city") or ""
    locality = details.get("city") or details.get("town") or details.get("village") or ""
    return GeoPoint(
        float(item["lat"]),
        float(item["lon"]),
        region,
        municipality,
        locality,
        municipality or locality or region,
        "osm",
        str(item.get("type") or ""),
        provider_name=str(item.get("name") or ""),
        provider_description=str(item.get("display_name") or ""),
        provider_kind=str(item.get("type") or ""),
        provider_text=str(item.get("display_name") or ""),
    )


def _2gis(address: str, timeout: int) -> GeoPoint | None:
    key = getattr(settings, "TWOGIS_API_KEY", "") or ""
    if not key:
        return None
    query = urllib.parse.urlencode({
        "q": address,
        "fields": "items.point,items.adm_div,items.full_name",
        "key": key,
    })
    data = _load(urllib.request.Request("https://catalog.api.2gis.com/3.0/items/geocode?" + query), timeout)
    items = ((data or {}).get("result") or {}).get("items") or []
    if not items:
        return None
    item = items[0]
    point = item.get("point") or {}
    if not point.get("lat") or not point.get("lon"):
        return None
    divisions = {str(part.get("type") or ""): str(part.get("name") or "") for part in item.get("adm_div") or []}
    region = divisions.get("region", "")
    municipality = divisions.get("district_area") or divisions.get("city") or ""
    locality = divisions.get("city") or divisions.get("settlement") or ""
    return GeoPoint(
        float(point["lat"]),
        float(point["lon"]),
        region,
        municipality,
        locality,
        municipality or locality or region,
        "2gis",
        str(item.get("type") or ""),
        provider_name=str(item.get("name") or ""),
        provider_description=str(item.get("full_name") or ""),
        provider_kind=str(item.get("type") or ""),
        provider_text=str(item.get("full_name") or address),
    )


PROVIDERS = {
    "yandex": _yandex,
    "dadata": _dadata,
    "dadata_suggest": _dadata_suggest,
    "dadata_suggest_scoped": _dadata_suggest_scoped,
    "osm": _osm,
    "2gis": _2gis,
}

# Nominatim и 2ГИС просят не долбить их чаще указанного; у Яндекса пауза
# добровольная — бесплатный ключ блокируют за пакетный характер обращений.
MIN_PAUSE_SECONDS = {"osm": 1.1, "2gis": 0.1, "yandex": 0.2}
