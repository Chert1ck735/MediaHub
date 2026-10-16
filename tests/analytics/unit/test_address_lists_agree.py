"""Адрес называется одинаково во всех списках.

Списков три и собирают их разные сервисы: «Адреса по теме» в карточке и в
отчёте, «Адреса в подпроблеме» справа и блок «Требует внимания» в отчёте.
Пока правила жили в каждом по отдельности, одна улица называлась в них
по-разному. Тест держит их вместе.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.modules.analytics.services.pain_detail_service import PainDetailService
from backend.modules.analytics.services.pain_slice_service import PainSliceService
from backend.modules.report.services.pdf_report_service import ReportPdfService

RAW = "микрорайон Мирный"
GEO = {
    "lat": 56.0501, "lon": 92.7100,
    "provider_name": "микрорайон Мирный", "locality": "посёлок Солонцы",
    "municipality": "Емельяновский район",
}


def _map_service():
    service = MagicMock()
    service.cache_snapshot.return_value = {}
    service.cached_geocode_for_context.side_effect = lambda *_a, **_k: dict(GEO)
    return service


async def _from_theme_list() -> str:
    """«Адреса по теме» — карточка боли и разбор тем в отчёте."""

    pain = uuid.uuid4()
    rows = [SimpleNamespace(
        pain_id=pain, case_name=RAW, mentions_count=3,
        public_region="Красноярский край", public_name="Емельяново", source_title="",
        sample_comment="", sample_address="", sample_address_hierarchy=None,
    )]
    service = PainSliceService.__new__(PainSliceService)
    service._db = MagicMock()
    service._comment_repository = MagicMock()

    async def _rows(*_a, **_k):
        return rows

    service._comment_repository.list_case_counts_by_pain = _rows
    with patch(
        "backend.modules.analytics.services.pain_slice_service.PainMapService",
        return_value=_map_service(),
    ):
        result = await service.collect_top_cases([pain])
    return result[str(pain)]["top_cases"][0]["title"]


async def _from_subproblem_list() -> str:
    """«Адреса в подпроблеме» — список справа в карточке."""

    service = PainDetailService.__new__(PainDetailService)
    service._db = MagicMock()
    service._comment_repository = MagicMock()
    rows = [SimpleNamespace(
        case_name=RAW, subcategory="качество дорог",
        public_region="Красноярский край", public_name="Емельяново", source_title="",
        text="комментарий", address="", address_hierarchy=None,
        publication_id=uuid.uuid4(), external_id="1", comment_id=uuid.uuid4(),
        publication_url="https://vk.com/wall-1_1",
        sentiment=SimpleNamespace(value="negative"), message_type="complaint",
    )]

    async def _rows(*_a, **_k):
        return rows

    service._comment_repository.list_case_rows_for_pain = _rows
    with patch(
        "backend.modules.analytics.services.pain_detail_service.PainMapService",
        return_value=_map_service(),
    ):
        grouped = await service._live_cases_by_subcategory(uuid.uuid4())
    return grouped["качество дорог"][0]["title"]


async def _from_report_attention() -> str:
    """«Требует внимания» — блок горящих адресов в отчёте."""

    service = ReportPdfService.__new__(ReportPdfService)
    service._db = MagicMock()
    service._comments = MagicMock()
    rows = [SimpleNamespace(
        case_name=RAW, public_region="Красноярский край", public_name="Емельяново",
        source_title="", mentions_count=3, negative_count=2, answered_count=0,
    )]

    async def _rows(*_a, **_k):
        return rows

    service._comments.list_burning_cases = _rows
    with patch(
        "backend.modules.analytics.services.pain_slice_service.PainMapService",
        return_value=_map_service(),
    ):
        result = await service._burning_cases(
            SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4()),
            period="week", public_social_link_id=None, municipality_name=None,
        )
    return result[0]["title"]


@pytest.mark.asyncio
async def test_every_list_names_the_place_the_same_way():
    titles = {
        "адреса по теме": await _from_theme_list(),
        "адреса в подпроблеме": await _from_subproblem_list(),
        "требует внимания": await _from_report_attention(),
    }

    assert len(set(titles.values())) == 1, f"подписи разошлись: {titles}"
    # Микрорайон не должен превращаться в улицу.
    assert next(iter(titles.values())).startswith("мкр.")
