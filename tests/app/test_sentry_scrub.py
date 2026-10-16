"""Секреты не должны уезжать в трекер ошибок."""
from backend.app.sentry import _scrub_text


def test_vk_token_is_removed_from_network_error():
    # Сетевые ошибки приходят с полным URL запроса вместе с токеном.
    text = (
        "HTTPSConnectionPool(host='api.vk.com', port=443): "
        "url: /method/groups.getById?v=5.199&access_token=vk1.a.QhPc8KVE4BUXd7vGk5YCO"
    )
    scrubbed = _scrub_text(text)
    assert "vk1.a." not in scrubbed
    assert "access_token=[filtered]" in scrubbed


def test_geocoder_key_is_removed():
    scrubbed = _scrub_text("https://geocode-maps.yandex.ru/1.x/?apikey=abc123&geocode=x")
    assert "abc123" not in scrubbed
    assert "geocode=x" in scrubbed


def test_database_password_and_email_still_removed():
    assert _scrub_text("postgresql://user:pass@db/mediahub") == "postgresql://***:***@db/mediahub"
    assert "<email>" in _scrub_text("письмо ivan@example.ru не ушло")
