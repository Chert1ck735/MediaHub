"""Адреса склеиваются по координатам, а не по тексту от модели.

В отчёте одна улица в одном посёлке выводилась четырьмя строками: модель
достаёт адрес каждый раз по-разному, геокодер разводит написания в близкие
точки, а ключ склейки строился из сырого текста.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.analytics.services import pain_slice_service
from backend.modules.analytics.utils import case_merge
from backend.modules.analytics.services.pain_slice_service import PainSliceService

PAIN_ID = uuid.uuid4()

# Три написания одной улицы — ровно как в отчёте с прода.
RAW_TITLES = [
    "Нагорная Солонцы, посёлок Солонцы",
    "Нагорная/дубовицкого, Солонцы, посёлок Солонцы",
    "Солонцы Нагорная/ Строительная, посёлок Солонцы",
]
CANONICAL = "Красноярский край, Емельяновский р-н, п. Солонцы, ул. Нагорная"


def _row(title: str, mentions: int):
    return SimpleNamespace(
        pain_id=PAIN_ID,
        case_name=title,
        public_region="Красноярский край",
        public_name="Администрация",
        source_title="Паблик",
        sample_comment="текст",
        sample_address="",
        sample_address_hierarchy=None,
        mentions_count=mentions,
    )


@pytest.fixture
def service(monkeypatch):
    fake_map = MagicMock()
    fake_map.cache_snapshot.return_value = {}
    # Одно место — координаты совпадают, названия разные.
    fake_map.cached_geocode_for_context.return_value = {
        "lat": 56.0001,
        "lon": 92.7002,
        "provider_name": CANONICAL,
    }
    monkeypatch.setattr(pain_slice_service, "PainMapService", lambda _db: fake_map)
    monkeypatch.setattr(pain_slice_service, "is_valid_case_title", lambda _t: True)
    monkeypatch.setattr(case_merge, "is_address_like", lambda _t, _g=None: True)
    monkeypatch.setattr(case_merge, "address_display_title", lambda title, _geo: title)

    svc = PainSliceService.__new__(PainSliceService)
    svc._db = MagicMock()
    svc._comment_repository = MagicMock()
    svc._comment_repository.list_case_counts_by_pain = AsyncMock(
        return_value=[_row(RAW_TITLES[0], 2), _row(RAW_TITLES[1], 2), _row(RAW_TITLES[2], 2)]
    )
    return svc


@pytest.mark.asyncio
async def test_same_place_written_differently_becomes_one_row(service):
    result = await service.collect_top_cases([PAIN_ID])

    cases = result[str(PAIN_ID)]["top_cases"]
    assert len(cases) == 1, [c["title"] for c in cases]
    # Упоминания суммируются, а не теряются при склейке.
    assert cases[0]["mentions_count"] == 6
    assert result[str(PAIN_ID)]["cases_count"] == 1


@pytest.mark.asyncio
async def test_different_places_stay_separate(service, monkeypatch):
    fake_map = MagicMock()
    fake_map.cache_snapshot.return_value = {}
    # Геокодер развёл адреса — значит, это разные места.
    fake_map.cached_geocode_for_context.side_effect = [
        {"lat": 56.0, "lon": 92.7, "provider_name": CANONICAL},
        {"lat": 55.9, "lon": 92.4, "provider_name": "Красноярский край, г. Дивногорск"},
    ]
    monkeypatch.setattr(pain_slice_service, "PainMapService", lambda _db: fake_map)
    service._comment_repository.list_case_counts_by_pain = AsyncMock(
        return_value=[_row(RAW_TITLES[0], 2), _row("ул. Борисевича", 3)]
    )

    result = await service.collect_top_cases([PAIN_ID])

    assert len(result[str(PAIN_ID)]["top_cases"]) == 2
