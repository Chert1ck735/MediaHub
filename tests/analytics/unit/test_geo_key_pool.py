import pytest

from backend.app.config import settings
from backend.modules.analytics.utils import geo_keys


@pytest.fixture
def pool(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GEO_CACHE_PATH", tmp_path / "geo_cache.json")
    monkeypatch.setattr(settings, "YANDEX_GEOCODER_KEY", "")
    monkeypatch.setattr(settings, "YANDEX_GEOCODER_KEYS", "key-one,key-two")
    monkeypatch.setattr(settings, "YANDEX_DAILY_BUDGET", 2)
    return geo_keys


def test_pool_switches_key_when_daily_budget_is_spent(pool):
    taken = []
    for _ in range(4):
        key = pool.take_key()
        taken.append(key)
        pool.note_request(key)

    assert taken == ["key-one", "key-one", "key-two", "key-two"]
    assert pool.take_key() is None


def test_rejected_key_is_skipped_until_next_day(pool):
    pool.note_rejected("key-one")

    assert pool.take_key() == "key-two"


def test_single_key_setting_still_works(pool, monkeypatch):
    monkeypatch.setattr(settings, "YANDEX_GEOCODER_KEYS", "")
    monkeypatch.setattr(settings, "YANDEX_GEOCODER_KEY", "solo")

    assert pool.configured_keys() == ["solo"]
    assert pool.take_key() == "solo"


def test_usage_hides_full_key(pool):
    pool.note_request("key-one")

    report = pool.usage()
    assert report["budget_per_key"] == 2
    assert report["keys"][0]["key"].endswith("ey-one")
    assert "key-one" not in report["keys"][0]["key"]
    assert report["keys"][0]["left"] == 1
