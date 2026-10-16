"""Список болей должен сужать снапшотные данные и по одному периоду.

Снапшот хранит подпроблемы и примеры комментариев за всё время. Пока сужение
включалось только фильтром площадки или округа, недельный отчёт показывал у
подпроблемы 2717 упоминаний при 122 обращениях во всей категории.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.analytics.services.pain_list_service import PainListService


def _service(monkeypatch):
    service = PainListService.__new__(PainListService)

    pain = SimpleNamespace(
        id=uuid.uuid4(),
        title="Дороги и транспорт",
        category="Дороги и транспорт",
        severity_level=SimpleNamespace(value="high"),
        status=SimpleNamespace(value="active"),
    )
    snapshot = SimpleNamespace(id=uuid.uuid4())

    service._snapshot_repository = MagicMock()
    service._snapshot_repository.get_latest_vk = AsyncMock(return_value=snapshot)
    service._snapshot_repository.list_pains = AsyncMock(return_value=[pain])

    service._pain_repository = MagicMock()
    service._pain_repository.get_strategies_map = AsyncMock(return_value={})
    service._pain_repository.get_evidence_urls_map = AsyncMock(return_value={})

    service._slice_service = MagicMock()
    service._slice_service.count_mentions = AsyncMock(return_value={str(pain.id): 122})
    service._slice_service.count_publications = AsyncMock(return_value={})
    service._slice_service.collect_comment_ids = AsyncMock(return_value={str(pain.id): {"c1"}})
    service._slice_service.collect_top_cases = AsyncMock(
        return_value={str(pain.id): {"top_cases": [], "cases_count": 0}}
    )
    service._slice_service.collect_comment_examples = AsyncMock(
        return_value={str(pain.id): [{"text": "Яму на Ленина так и не закрыли", "url": ""}]}
    )
    service._slice_service.severity_from_share = MagicMock(return_value="high")

    service._context_service = MagicMock()
    service._context_service.build = MagicMock(return_value={"subproblems": [], "subproblem_items": []})
    service._context_service.filter_by_comment_ids = MagicMock(
        return_value={"subproblems": [], "subproblem_items": []}
    )
    return service, pain


@pytest.mark.asyncio
async def test_period_alone_narrows_snapshot_context(monkeypatch):
    service, _pain = _service(monkeypatch)

    await service.list_pains(MagicMock(), period="week")

    # Оба шага обязаны отработать: без них в отчёт попадают цифры за всё время.
    assert service._slice_service.collect_comment_ids.await_count == 1
    assert service._context_service.filter_by_comment_ids.call_count == 1


@pytest.mark.asyncio
async def test_all_time_keeps_snapshot_as_is(monkeypatch):
    service, _pain = _service(monkeypatch)

    await service.list_pains(MagicMock(), period="all")

    # Сужать нечем и незачем — лишний запрос к базе не делаем.
    assert service._slice_service.collect_comment_ids.await_count == 0
    assert service._context_service.filter_by_comment_ids.call_count == 0
    assert service._slice_service.collect_comment_examples.await_count == 0


@pytest.mark.asyncio
async def test_filtered_report_keeps_quotes(monkeypatch):
    """Отсев по видимым id вырезает чужие примеры — раздел не должен пустеть."""

    service, pain = _service(monkeypatch)

    items = await service.list_pains(MagicMock(), period="week")

    assert service._slice_service.collect_comment_examples.await_count == 1
    assert items[0].comment_examples, "в отчёте не осталось ни одной цитаты"
