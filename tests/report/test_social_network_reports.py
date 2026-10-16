import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.report.repositories.post_repository import ReportPostRepository
from backend.modules.report.repositories.audience_repository import AudienceRepository
from backend.modules.report.services.preview_service import ReportPreviewService
from backend.modules.report.schema import ReportPreviewRequest
from backend.modules.analytics.utils.comment_examples import vk_comment_url


@pytest.mark.parametrize("network", ["vk", "ok", "telegram"])
async def test_report_sql_restricts_network_and_selected_sources(network):
    result = MagicMock()
    result.all.return_value = []
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    source = uuid.uuid4()
    await ReportPostRepository(db).load_vk_posts(uuid.uuid4(), str(source), platform=network)
    await AudienceRepository(db).compute_activity(uuid.uuid4(), str(source), platform=network)
    for call in db.execute.call_args_list:
        sql = str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        assert f"social_networks.code = '{network}'" in sql
        assert source.hex in sql.replace("-", "")


@pytest.mark.parametrize("network,label", [("vk", "VK"), ("ok", "Одноклассники"), ("telegram", "TG")])
async def test_empty_report_returns_zero_and_preserves_filters(network, label):
    service = ReportPreviewService(None)
    service._posts.load_vk_posts = AsyncMock(return_value=[])
    service._audience.compute_activity = AsyncMock(return_value=(None, None))
    payload = ReportPreviewRequest(platform=network, public_social_link_id=str(uuid.uuid4()))
    response = await service.preview(SimpleNamespace(organization_id=uuid.uuid4()), payload)
    assert response.total_posts == 0
    assert response.all_posts == []
    assert response.platform == label
    for method in (service._posts.load_vk_posts, service._audience.compute_activity):
        assert method.call_args.kwargs["platform"] == network
        assert method.call_args.kwargs["public_social_link_id"] == payload.public_social_link_id


def test_telegram_comment_link_uses_discussion_message_id():
    assert vk_comment_url("https://t.me/channel/42", "42:123") == "https://t.me/channel/42?comment=123"
    assert vk_comment_url("https://vk.com/wall-1_2?foo=1", "3") == "https://vk.com/wall-1_2?foo=1&reply=3"
    assert vk_comment_url("https://ok.ru/group/1/topic/2", "3") == "https://ok.ru/group/1/topic/2"


async def test_audience_aggregates_from_one_query():
    result = MagicMock()
    result.all.return_value = [(1, 9, 3), (2, 9, 5), (2, 10, 1)]
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    window, heatmap = await AudienceRepository(db).compute_activity(uuid.uuid4(), platform="telegram")
    assert db.execute.await_count == 1
    assert sum(map(sum, heatmap)) == 9
    assert heatmap[1][9] == 3
    assert heatmap[2][9] == 5
    assert window
