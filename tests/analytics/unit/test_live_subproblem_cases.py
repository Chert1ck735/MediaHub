"""Список «Адреса в подпроблеме» собирается живой выборкой.

Строки взяты из карточки «Качество дорог»: одна улица приходила туда
несколькими написаниями, а рядом лежали названия территорий.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.modules.analytics.services.pain_detail_service import PainDetailService


GEO = {
    "Дубовицкого, посёлок Солонцы": {"lat": 56.0501, "lon": 92.7100,
                                     "provider_name": "улица Дубовицкого", "locality": "Солонцы"},
    "Дубовицкого/Нагорная - Многострадальные, Солонцы": {"lat": 56.0530, "lon": 92.7166,
                                     "provider_name": "Улица Дубовицкого", "locality": "Солонцы"},
    "ул. Нагорная В Солонцах У Складов Янта": {"lat": 56.0570, "lon": 92.7210,
                                     "provider_name": "Нагорная улица", "locality": "Солонцы"},
    "Город Дивногорск": {"lat": 55.9577, "lon": 92.3801, "locality": "Дивногорск",
                         "provider_name": "Дивногорск"},
    "ЗАТО Г. Железногорск": {"lat": 56.2509, "lon": 93.5326, "locality": "Железногорск",
                             "provider_name": "Железногорск"},
    "Центр Города Красноярска": {"lat": 56.0100, "lon": 92.8500, "locality": "Красноярск",
                                 "provider_name": "Красноярск"},
}


def _row(title, cid):
    return SimpleNamespace(
        case_name=title, subcategory="качество дорог",
        public_region="Красноярский край", public_name="Емельяново", source_title="",
        text=f"комментарий {cid}", address="", address_hierarchy=None,
        publication_id=uuid.uuid4(), external_id=cid, comment_id=uuid.uuid4(),
        publication_url="https://vk.com/wall-1_1",
        sentiment=SimpleNamespace(value="negative"), message_type="complaint",
    )


async def _cases():
    service = PainDetailService.__new__(PainDetailService)
    service._db = MagicMock()
    service._comment_repository = MagicMock()

    rows = [_row(title, str(index)) for index, title in enumerate(GEO)]

    async def _rows(*_args, **_kwargs):
        return rows

    service._comment_repository.list_case_rows_for_pain = _rows

    map_service = MagicMock()
    map_service.cache_snapshot.return_value = {}
    map_service.cached_geocode_for_context.side_effect = lambda ctx, _c: GEO.get(ctx.case_name)

    with patch(
        "backend.modules.analytics.services.pain_detail_service.PainMapService",
        return_value=map_service,
    ):
        grouped = await service._live_cases_by_subcategory(uuid.uuid4())
    return grouped.get("качество дорог", [])


@pytest.mark.asyncio
async def test_one_street_is_one_row():
    cases = await _cases()

    titles = [case["title"] for case in cases]
    assert len(titles) == len(set(titles)), f"одинаковые строки: {titles}"

    dubovitskogo = [c for c in cases if "убовицк" in c["title"]]
    assert len(dubovitskogo) == 1, f"улица осталась несколькими строками: {dubovitskogo}"
    assert dubovitskogo[0]["mentions_count"] == 2
    assert len(dubovitskogo[0]["comment_examples"]) == 2


@pytest.mark.asyncio
async def test_territories_are_gone():
    titles = " | ".join(case["title"] for case in await _cases())

    for territory in ("Дивногорск", "Железногорск", "Красноярска"):
        assert territory not in titles, f"территория осталась в адресах: {titles}"
