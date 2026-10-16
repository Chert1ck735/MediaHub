import pytest

from backend.modules.telegram.errors import InvalidTelegramLinkError
from backend.modules.telegram.links.links import parse_telegram_link


def test_parses_channel_and_normalizes_preview_url():
    ref = parse_telegram_link("https://t.me/s/Example_Channel/")

    assert ref.username == "Example_Channel"
    assert ref.canonical_url == "https://t.me/Example_Channel"
    assert ref.post_id is None


def test_parses_single_post_url():
    ref = parse_telegram_link("telegram.me/example_channel/42")

    assert ref.username == "example_channel"
    assert ref.post_id == 42


@pytest.mark.parametrize("url", ["https://t.me/+private", "https://t.me/c/123/1", "https://example.com/news"])
def test_rejects_private_and_non_telegram_urls(url):
    with pytest.raises(InvalidTelegramLinkError):
        parse_telegram_link(url)
