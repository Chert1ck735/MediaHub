"""Отказ ключа не должен стоить запроса: переходим на следующий сразу."""
from __future__ import annotations

import urllib.error

import pytest

from backend.modules.analytics.utils import geo_keys, geocode


@pytest.fixture
def pool(tmp_path, monkeypatch):
    monkeypatch.setattr(geo_keys, "_state_path", lambda: tmp_path / "keys.json")
    geo_keys.set_runtime_keys(["key-one", "key-two", "key-three"])
    yield
    geo_keys.set_runtime_keys([])


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://geocode-maps.yandex.ru/", code, "", {}, None)


def test_rejected_key_is_replaced_within_one_call(pool, monkeypatch):
    used: list[str] = []

    def fake_load(request, *, timeout, provider, address):
        key = request.full_url.split("apikey=")[1].split("&")[0]
        used.append(key)
        if key == "key-one":
            raise _http_error(403)
        return {"response": {"GeoObjectCollection": {"featureMember": []}}}

    monkeypatch.setattr(geocode, "_load_provider_json", fake_load)

    assert geocode._yandex_response("Красноярск", 5) is not None
    assert used == ["key-one", "key-two"]
    assert geo_keys.usage()["keys"][0]["blocked"] is True


def test_other_errors_do_not_burn_keys(pool, monkeypatch):
    def fake_load(request, *, timeout, provider, address):
        raise _http_error(500)

    monkeypatch.setattr(geocode, "_load_provider_json", fake_load)

    with pytest.raises(urllib.error.HTTPError):
        geocode._yandex_response("Красноярск", 5)
    assert all(not row["blocked"] for row in geo_keys.usage()["keys"])


def test_gives_up_when_every_key_is_rejected(pool, monkeypatch):
    def fake_load(request, *, timeout, provider, address):
        raise _http_error(403)

    monkeypatch.setattr(geocode, "_load_provider_json", fake_load)

    assert geocode._yandex_response("Красноярск", 5) is None
    assert all(row["blocked"] for row in geo_keys.usage()["keys"])
