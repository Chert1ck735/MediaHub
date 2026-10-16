import hashlib

import pytest
import requests

from backend.modules.ok.utils.api_client import OkApiClient
from backend.modules.ok.utils.errors import OkApiError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append({"url": url, "data": data, "timeout": timeout})
        payload = self.payloads.pop(0)
        if isinstance(payload, requests.exceptions.RequestException):
            raise payload
        return FakeResponse(payload)


@pytest.fixture(autouse=True)
def _ok_credentials(monkeypatch):
    base = "backend.modules.ok.utils.api_client.settings"
    monkeypatch.setattr(f"{base}.OK_APPLICATION_KEY", "APPKEY")
    monkeypatch.setattr(f"{base}.OK_APPLICATION_SECRET_KEY", "SECRET")
    monkeypatch.setattr(f"{base}.OK_ACCESS_TOKEN", "TOKEN")
    monkeypatch.setattr(f"{base}.OK_INTER_REQUEST_DELAY", 0.0)


def test_call_signs_request_and_omits_token_from_signature():
    session = FakeSession([{"ok": True}])
    client = OkApiClient(session=session)

    client.call("group.getInfo", {"uids": "123"})

    sent = session.calls[0]["data"]
    session_secret = hashlib.md5(b"TOKENSECRET").hexdigest().lower()
    signed = {k: v for k, v in sent.items() if k not in {"access_token", "sig"}}
    base = "".join(f"{k}={signed[k]}" for k in sorted(signed))
    expected = hashlib.md5(f"{base}{session_secret}".encode()).hexdigest().lower()

    assert sent["sig"] == expected
    assert sent["access_token"] == "TOKEN"
    assert sent["format"] == "json"


def test_call_drops_none_params():
    session = FakeSession([{"ok": True}])
    client = OkApiClient(session=session)

    client.call("group.getStatTopics", {"gid": "1", "anchor": None})

    assert "anchor" not in session.calls[0]["data"]


def test_call_raises_on_error_code():
    client = OkApiClient(session=FakeSession([{"error_code": 100, "error_msg": "PARAM"}]))

    with pytest.raises(OkApiError) as exc:
        client.call("group.getInfo", {})

    assert exc.value.code == 100


def test_call_retries_service_error(monkeypatch):
    monkeypatch.setattr("backend.modules.ok.utils.api_client.RETRY_DELAY_SEC", 0)
    session = FakeSession([{"error_code": 2, "error_msg": "SERVICE"}, {"ok": True}])
    client = OkApiClient(session=session)

    assert client.call("group.getInfo", {}) == {"ok": True}
    assert len(session.calls) == 2


def test_get_group_raises_when_not_found():
    client = OkApiClient(session=FakeSession([[]]))

    with pytest.raises(OkApiError):
        client.get_group("missing")


def test_fetch_all_stat_topics_follows_anchor():
    session = FakeSession(
        [
            {"topics": [{"id": "1"}, {"id": "2"}], "anchor": "A1", "has_more": True, "totalCount": 3},
            {"topics": [{"id": "3"}], "anchor": None, "has_more": False, "totalCount": 3},
        ]
    )
    client = OkApiClient(session=session)

    topics = client.fetch_all_stat_topics("70000")

    assert [t["id"] for t in topics] == ["1", "2", "3"]


def test_fetch_all_stat_topics_stops_on_repeated_anchor():
    """OK иногда отдаёт has_more=true с тем же anchor — не зацикливаемся."""
    session = FakeSession(
        [
            {"topics": [{"id": "1"}], "anchor": "SAME", "has_more": True},
            {"topics": [{"id": "2"}], "anchor": "SAME", "has_more": True},
        ]
    )
    client = OkApiClient(session=session)

    topics = client.fetch_all_stat_topics("70000")

    assert [t["id"] for t in topics] == ["1", "2"]
    assert len(session.calls) == 2


def test_fetch_all_stat_topics_respects_max_topics():
    session = FakeSession([{"topics": [{"id": "1"}, {"id": "2"}], "anchor": "A", "has_more": True}])
    client = OkApiClient(session=session)

    assert len(client.fetch_all_stat_topics("70000", max_topics=1)) == 1


def test_fetch_all_comments_stops_on_partial_page():
    session = FakeSession([{"comments": [{"id": "c1"}]}])
    client = OkApiClient(session=session)

    assert client.fetch_all_comments("111") == [{"id": "c1"}]
    assert len(session.calls) == 1


def test_fetch_all_comments_reads_legacy_key():
    """В схеме OK ключ описан как commentss; читаем оба варианта."""
    client = OkApiClient(session=FakeSession([{"commentss": [{"id": "c1"}]}]))

    assert client.fetch_all_comments("111") == [{"id": "c1"}]


def test_get_mediatopics_batches_ids(monkeypatch):
    monkeypatch.setattr("backend.modules.ok.utils.api_client.MEDIATOPIC_BATCH_SIZE", 2)
    session = FakeSession([{"media_topics": [{"id": "1"}, {"id": "2"}]}, {"media_topics": [{"id": "3"}]}])
    client = OkApiClient(session=session)

    topics = client.get_mediatopics(["1", "2", "3"])

    assert [t["id"] for t in topics] == ["1", "2", "3"]
    assert session.calls[0]["data"]["topic_ids"] == "1,2"
    assert session.calls[1]["data"]["topic_ids"] == "3"


def test_missing_credentials_raise(monkeypatch):
    monkeypatch.setattr("backend.modules.ok.utils.api_client.settings.OK_ACCESS_TOKEN", "")
    client = OkApiClient(session=FakeSession([]))

    with pytest.raises(OkApiError, match="не настроена"):
        client.call("group.getInfo", {})
