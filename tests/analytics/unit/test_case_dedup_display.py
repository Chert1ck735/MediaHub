"""Адреса, одинаковые на вид, не должны попадать в отчёт дважды.

Геокодер разводит разные написания одной улицы дальше, чем на квартал,
поэтому склейки по координатам не хватало: в отчёте шли две строки с
одинаковым текстом.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.modules.analytics.services.pain_slice_service import PainSliceService


def _row(pain_id, title, mentions):
    return SimpleNamespace(
        pain_id=pain_id,
        case_name=title,
        mentions_count=mentions,
        public_region="Красноярский край",
        public_name="Ачинск",
        source_title="",
        sample_comment="",
        sample_address="",
        sample_address_hierarchy=None,
    )


@pytest.mark.asyncio
async def test_same_looking_addresses_merge():
    pain_id = uuid.uuid4()
    rows = [
        _row(pain_id, "ул. Ленина, 5", 4),
        _row(pain_id, "улица Ленина 5", 3),
    ]

    service = PainSliceService.__new__(PainSliceService)
    service._db = MagicMock()
    service._comment_repository = MagicMock()

    async def _rows(*_args, **_kwargs):
        return rows

    service._comment_repository.list_case_counts_by_pain = _rows

    map_service = MagicMock()
    map_service.cache_snapshot.return_value = {}
    # Координаты разные: между написаниями больше квартала.
    coords = iter([
        {"lat": 56.2690, "lon": 90.4990},
        {"lat": 56.2712, "lon": 90.5031},
    ])
    map_service.cached_geocode_for_context.side_effect = lambda *_a, **_k: next(coords)

    with patch(
        "backend.modules.analytics.services.pain_slice_service.PainMapService",
        return_value=map_service,
    ), patch(
        "backend.modules.analytics.utils.case_merge.address_display_title",
        side_effect=lambda title, geo=None: "Улица Ленина, 5",
    ):
        result = await service.collect_top_cases([pain_id])

    cases = result[str(pain_id)]["top_cases"]
    assert result[str(pain_id)]["cases_count"] == 1, "адрес попал в отчёт дважды"
    assert cases[0]["mentions_count"] == 7, "упоминания не сложились"


@pytest.mark.asyncio
async def test_one_street_written_differently_merges():
    """«ул. Дубовицкого» и «Дубовицкого, посёлок Солонцы» — одна улица."""

    pain_id = uuid.uuid4()
    rows = [
        _row(pain_id, "ул. Дубовицкого", 2),
        _row(pain_id, "Дубовицкого, посёлок Солонцы", 1),
    ]

    service = PainSliceService.__new__(PainSliceService)
    service._db = MagicMock()
    service._comment_repository = MagicMock()

    async def _rows(*_args, **_kwargs):
        return rows

    service._comment_repository.list_case_counts_by_pain = _rows

    map_service = MagicMock()
    map_service.cache_snapshot.return_value = {}
    # Геокодер свёл оба написания к одному объекту, но точки поставил разные.
    geo = iter([
        {"lat": 56.0501, "lon": 92.7100, "provider_name": "улица Дубовицкого, Солонцы"},
        {"lat": 56.0530, "lon": 92.7166, "provider_name": "Улица Дубовицкого, Солонцы"},
    ])
    map_service.cached_geocode_for_context.side_effect = lambda *_a, **_k: next(geo)

    with patch(
        "backend.modules.analytics.services.pain_slice_service.PainMapService",
        return_value=map_service,
    ):
        result = await service.collect_top_cases([pain_id])

    assert result[str(pain_id)]["cases_count"] == 1
    assert result[str(pain_id)]["top_cases"][0]["mentions_count"] == 3


@pytest.mark.asyncio
async def test_same_street_name_in_different_villages_stays_apart():
    """«ул. Комсомольская» есть в четырёх сёлах края — это разные улицы."""

    pain_id = uuid.uuid4()
    # Улицы приходят из пабликов разных территорий — контекст у них разный.
    first = _row(pain_id, "ул. Комсомольская", 2)
    first.public_name = "Емельяново"
    second = _row(pain_id, "ул. Комсомольская", 1)
    second.public_name = "Шушенское"
    rows = [first, second]

    service = PainSliceService.__new__(PainSliceService)
    service._db = MagicMock()
    service._comment_repository = MagicMock()

    async def _rows(*_args, **_kwargs):
        return rows

    service._comment_repository.list_case_counts_by_pain = _rows

    map_service = MagicMock()
    map_service.cache_snapshot.return_value = {}
    # Разные сёла: между точками больше двухсот километров.
    geo = iter([
        {"lat": 56.0100, "lon": 92.8600},
        {"lat": 58.2000, "lon": 92.5000},
    ])
    map_service.cached_geocode_for_context.side_effect = lambda *_a, **_k: next(geo)

    with patch(
        "backend.modules.analytics.services.pain_slice_service.PainMapService",
        return_value=map_service,
    ), patch(
        "backend.modules.analytics.utils.case_merge.address_display_title",
        side_effect=lambda title, geo=None: "Улица Комсомольская",
    ):
        result = await service.collect_top_cases([pain_id])

    assert result[str(pain_id)]["cases_count"] == 2, "разные улицы слиплись в одну"


@pytest.mark.asyncio
async def test_street_and_street_with_village_merge():
    """«ул. Нагорная (6)» и «Нагорная, посёлок Солонцы (2)» — одна улица."""

    pain_id = uuid.uuid4()
    first = _row(pain_id, "ул. Нагорная", 6)
    first.public_name = "Солонцы"
    second = _row(pain_id, "Нагорная Солонцы, посёлок Солонцы", 2)
    second.public_name = "Емельяново"
    rows = [first, second]

    service = PainSliceService.__new__(PainSliceService)
    service._db = MagicMock()
    service._comment_repository = MagicMock()

    async def _rows(*_args, **_kwargs):
        return rows

    service._comment_repository.list_case_counts_by_pain = _rows

    map_service = MagicMock()
    map_service.cache_snapshot.return_value = {}
    # Геокодер дал разные объекты и точки в одном селе.
    geo = iter([
        {"lat": 56.0501, "lon": 92.7100, "provider_name": "Нагорная улица", "locality": "Солонцы"},
        {"lat": 56.0540, "lon": 92.7180, "provider_name": "Нагорная, Солонцы", "locality": "Солонцы"},
    ])
    titles = iter(["ул. Нагорная", "Нагорная, посёлок Солонцы"])
    map_service.cached_geocode_for_context.side_effect = lambda *_a, **_k: next(geo)

    with patch(
        "backend.modules.analytics.services.pain_slice_service.PainMapService",
        return_value=map_service,
    ), patch(
        "backend.modules.analytics.utils.case_merge.address_display_title",
        side_effect=lambda title, geo=None: next(titles),
    ):
        result = await service.collect_top_cases([pain_id])

    assert result[str(pain_id)]["cases_count"] == 1, "улица осталась двумя строками"
    assert result[str(pain_id)]["top_cases"][0]["mentions_count"] == 8


@pytest.mark.asyncio
async def test_rows_without_pain_are_accepted():
    """Горящие адреса отчёта приходят без pain_id — на этом падал отчёт."""

    # Ровно те поля, что отдаёт запрос горящих адресов: ни pain_id,
    # ни образца комментария, ни разобранного адреса там нет.
    row = SimpleNamespace(
        case_name="ул. Дубовицкого",
        public_region="Красноярский край",
        public_name="Емельяново",
        source_title="",
        mentions_count=3,
        negative_count=2,
        answered_count=0,
    )

    service = PainSliceService.__new__(PainSliceService)
    service._db = MagicMock()

    map_service = MagicMock()
    map_service.cache_snapshot.return_value = {}
    map_service.cached_geocode_for_context.return_value = {
        "lat": 56.05, "lon": 92.71, "provider_name": "улица Дубовицкого", "locality": "Солонцы",
    }

    with patch(
        "backend.modules.analytics.services.pain_slice_service.PainMapService",
        return_value=map_service,
    ):
        keys = service.case_keys([row])

    assert "" in keys, "строки без боли должны попадать в общую группу"
    assert list(keys[""].values())[0][1]


@pytest.mark.asyncio
async def test_one_street_is_named_the_same_in_every_theme():
    """В «Дорогах» и «ЖКХ» улица должна называться одинаково."""

    roads, utilities = uuid.uuid4(), uuid.uuid4()

    def _geo(lat, lon, name):
        return {"lat": lat, "lon": lon, "provider_name": name, "locality": "посёлок Солонцы"}

    data = [
        (roads, "Нагорная Солонцы, посёлок Солонцы", 4, _geo(56.059464, 92.851368, "Нагорная улица, Солонцы")),
        (roads, "ул. Нагорная", 3, _geo(56.05873, 92.852967, "Нагорная улица")),
        (utilities, "ул. Нагорная", 2, _geo(56.05873, 92.852967, "Нагорная улица")),
    ]
    rows = [_row(pain, title, mentions) for pain, title, mentions, _ in data]
    by_title = {title: geo for _pain, title, _n, geo in data}

    service = PainSliceService.__new__(PainSliceService)
    service._db = MagicMock()
    service._comment_repository = MagicMock()

    async def _rows(*_args, **_kwargs):
        return rows

    service._comment_repository.list_case_counts_by_pain = _rows

    map_service = MagicMock()
    map_service.cache_snapshot.return_value = {}
    map_service.cached_geocode_for_context.side_effect = lambda ctx, _c: by_title.get(ctx.case_name)

    with patch(
        "backend.modules.analytics.services.pain_slice_service.PainMapService",
        return_value=map_service,
    ):
        result = await service.collect_top_cases([roads, utilities], limit_per_pain=10)

    in_roads = result[str(roads)]["top_cases"]
    in_utilities = result[str(utilities)]["top_cases"]

    assert len(in_roads) == 1 and in_roads[0]["mentions_count"] == 7
    assert in_roads[0]["title"] == in_utilities[0]["title"], "улица названа по-разному в темах"
