"""Фолбэк для токенов без прав админа: id тем из публичной ленты m.ok.ru."""

import pytest
import requests

from backend.modules.ok.utils.api_client import OkApiClient
from backend.modules.ok.utils.errors import OkApiError

GID = "53458237653184"
SHORT = "digitalkrsk24"


class FakeHtmlResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class FakeHtmlSession:
    """Отдаёт HTML-страницы по очереди и запоминает запрошенные URL."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        page = self.pages.pop(0)
        if isinstance(page, requests.exceptions.RequestException):
            raise page
        if isinstance(page, FakeHtmlResponse):
            return page
        return FakeHtmlResponse(page)


def _page(topic_ids, *, more=None, shortname_links=False, foreign=None):
    """Собирает HTML, похожий на публичную ленту m.ok.ru."""

    prefix = f"/{SHORT}" if shortname_links else f"/group/{GID}"
    links = "".join(f'<a href="{prefix}/topic/{tid}">post</a>' for tid in topic_ids)
    if foreign:
        links += "".join(f'<a href="/othergroup/topic/{tid}">ad</a>' for tid in foreign)
    if more:
        links += (
            f'<a href="/dk;jsessionid=abc?st.cmd=altGroupMain&amp;st.groupId={GID}'
            f"&amp;st.frwd=on&amp;st.mrkId={more}&amp;tkn=1\">more</a>"
        )
    return f"<html><body>{links}</body></html>"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.ok.utils.api_client.settings.OK_INTER_REQUEST_DELAY", 0.0
    )


def test_collects_ids_in_order_and_follows_more_link():
    session = FakeHtmlSession(
        [
            _page(["111", "222"], more="M1"),
            _page(["222", "333"]),  # 222 — дубль (закреп), должен отброситься
        ]
    )
    client = OkApiClient(session=session)

    ids = client.fetch_public_topic_ids(GID, shortname=SHORT)

    assert ids == ["111", "222", "333"]
    assert session.urls[0] == f"https://m.ok.ru/group/{GID}"
    # Ссылка «Ещё» разэкранирована (&amp; -> &) и ведёт на m.ok.ru.
    assert session.urls[1].startswith("https://m.ok.ru/dk;jsessionid=")
    assert "st.mrkId=M1" in session.urls[1] and "&amp;" not in session.urls[1]


def test_accepts_shortname_links_and_skips_foreign_topics():
    session = FakeHtmlSession(
        [_page(["111"], shortname_links=True, foreign=["999"])]
    )
    client = OkApiClient(session=session)

    assert client.fetch_public_topic_ids(GID, shortname=SHORT) == ["111"]


def test_respects_max_topics():
    session = FakeHtmlSession([_page(["1", "2", "3"], more="M1")])
    client = OkApiClient(session=session)

    ids = client.fetch_public_topic_ids(GID, max_topics=2)

    assert ids == ["1", "2"]
    assert len(session.urls) == 1  # за «Ещё» не ходили


def test_stops_when_page_has_no_new_ids():
    """OK может крутить по кругу: та же страница с тем же маркером."""
    session = FakeHtmlSession(
        [_page(["1"], more="SAME"), _page(["1"], more="SAME")]
    )
    client = OkApiClient(session=session)

    assert client.fetch_public_topic_ids(GID) == ["1"]
    assert len(session.urls) == 2


def test_first_page_error_raises():
    client = OkApiClient(session=FakeHtmlSession([FakeHtmlResponse("", 403)]))

    with pytest.raises(OkApiError, match="недоступна"):
        client.fetch_public_topic_ids(GID)


def test_pagination_error_returns_collected():
    session = FakeHtmlSession(
        [_page(["1"], more="M1"), requests.exceptions.ConnectionError("boom")]
    )
    client = OkApiClient(session=session)

    assert client.fetch_public_topic_ids(GID) == ["1"]
