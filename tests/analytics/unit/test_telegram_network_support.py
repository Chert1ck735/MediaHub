"""Регрессия: Telegram должен проходить в аналитику и автопарсер."""

from backend.modules.analytics.constants import ANALYTICS_NETWORK_CODES
from backend.modules.autoparse.repository import SUPPORTED_NETWORKS


def test_telegram_comments_are_in_analytics_scope():
    assert "telegram" in ANALYTICS_NETWORK_CODES


def test_telegram_links_are_in_autoparse_scope():
    assert "telegram" in SUPPORTED_NETWORKS
