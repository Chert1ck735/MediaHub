"""Блок «Требует внимания» в отчёте.

Строки горящих адресов приходят своим запросом: у них нет ни pain_id, ни
образца комментария. На этом отчёт падал с AttributeError и отдавал 500.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.modules.report.services.pdf_report_service import ReportPdfService


def _row(title, *, negative, mentions, answered=0):
    return SimpleNamespace(
        case_name=title,
        public_region="Красноярский край",
        public_name="Емельяново",
        source_title="",
        mentions_count=mentions,
        negative_count=negative,
        answered_count=answered,
    )


GEO = {
    "ул. Дубовицкого": {"lat": 56.0501, "lon": 92.7100,
                        "provider_name": "улица Дубовицкого", "locality": "Солонцы"},
    "Дубовицкого, посёлок Солонцы": {"lat": 56.0530, "lon": 92.7166,
                        "provider_name": "Улица Дубовицкого", "locality": "Солонцы"},
    "Город Дивногорск": {"lat": 55.9577, "lon": 92.3801,
                        "provider_name": "Дивногорск", "locality": "Дивногорск"},
}


async def _burning(rows):
    service = ReportPdfService.__new__(ReportPdfService)
    service._db = MagicMock()
    service._comments = MagicMock()

    async def _rows(*_args, **_kwargs):
        return rows

    service._comments.list_burning_cases = _rows

    map_service = MagicMock()
    map_service.cache_snapshot.return_value = {}
    map_service.cached_geocode_for_context.side_effect = lambda ctx, _c: GEO.get(ctx.case_name)

    with patch(
        "backend.modules.analytics.services.pain_slice_service.PainMapService",
        return_value=map_service,
    ):
        return await service._burning_cases(
            SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4()),
            period="week",
            public_social_link_id=None,
            municipality_name=None,
        )


@pytest.mark.asyncio
async def test_report_block_builds_without_pain_id():
    result = await _burning([_row("ул. Дубовицкого", negative=2, mentions=3)])

    assert len(result) == 1
    assert result[0]["negative"] == 2


@pytest.mark.asyncio
async def test_one_street_written_twice_is_one_line():
    result = await _burning([
        _row("ул. Дубовицкого", negative=2, mentions=3),
        _row("Дубовицкого, посёлок Солонцы", negative=1, mentions=1),
    ])

    assert len(result) == 1, f"улица попала в блок дважды: {result}"
    assert result[0]["negative"] == 3


@pytest.mark.asyncio
async def test_territory_does_not_reach_the_block():
    result = await _burning([_row("Город Дивногорск", negative=4, mentions=9)])

    assert result == []


@pytest.mark.asyncio
async def test_answered_case_is_skipped():
    result = await _burning([_row("ул. Дубовицкого", negative=3, mentions=4, answered=1)])

    assert result == []
