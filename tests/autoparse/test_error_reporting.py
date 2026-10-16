"""Стойкая ошибка ссылки уходит в трекер один раз, а не каждый тик."""
import uuid

import pytest

from backend.modules.autoparse.repository import AutoParseRepository

VK_ERROR = "IngestionError: VK не распознал screen_name 'dikson_sovet'"


class _Link:
    def __init__(self, error: str | None = None):
        self.last_autoparse_error = error


class _Db:
    """Минимальная сессия: репозиторию нужен только get по ссылке."""

    def __init__(self, link: _Link | None):
        self.link = link

    async def get(self, _model, _link_id):
        return self.link


@pytest.mark.asyncio
async def test_repeated_error_is_reported_once():
    """Ссылка висит сломанной месяцами — трекер должен узнать об этом один раз."""

    repo = AutoParseRepository(_Db(_Link()))
    link_id = uuid.uuid4()

    assert await repo.record_error(link_id, VK_ERROR) is True
    assert await repo.record_error(link_id, VK_ERROR) is False
    assert await repo.record_error(link_id, VK_ERROR) is False


@pytest.mark.asyncio
async def test_changed_error_is_reported_again():
    link = _Link()
    repo = AutoParseRepository(_Db(link))
    link_id = uuid.uuid4()

    await repo.record_error(link_id, VK_ERROR)

    assert await repo.record_error(link_id, "VkApiError: rate limit") is True
    assert link.last_autoparse_error == "VkApiError: rate limit"


@pytest.mark.asyncio
async def test_recovery_then_failure_is_reported():
    """После успешного прохода ошибка снова становится новостью."""

    link = _Link()
    repo = AutoParseRepository(_Db(link))
    link_id = uuid.uuid4()

    await repo.record_error(link_id, VK_ERROR)
    await repo.record_error(link_id, None)

    assert await repo.record_error(link_id, VK_ERROR) is True


@pytest.mark.asyncio
async def test_missing_link_is_not_reported():
    repo = AutoParseRepository(_Db(None))

    assert await repo.record_error(uuid.uuid4(), VK_ERROR) is False
