"""Классовый OK API-клиент.

Содержит только HTTP-вызовы Одноклассников и пагинацию OK API.
Не знает про FastAPI, SQLAlchemy и бизнес-логику приложения.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import logging
import re
import time
from datetime import datetime
from typing import Any, Callable, Optional

import requests

from backend.app.config import settings
from backend.modules.ok.utils.constants import (
    API_BASE,
    COMMENTS_PAGE_SIZE,
    GROUP_TOPIC_DISCUSSION_TYPE,
    INTER_REQUEST_DELAY_SEC,
    MAX_RETRIES,
    MEDIATOPIC_BATCH_SIZE,
    OK_GROUP_FIELDS,
    OK_MEDIATOPIC_FIELDS,
    OK_MOBILE_BASE,
    OK_MOBILE_MAX_PAGES,
    OK_MOBILE_USER_AGENT,
    OK_SERVICE_ERROR_CODE,
    OK_STAT_TOPIC_FIELDS,
    RETRY_DELAY_SEC,
    TOPICS_PAGE_SIZE,
)
from backend.modules.ok.utils.errors import OkApiError

logger = logging.getLogger(__name__)

# Ссылка «Ещё» в публичной ленте: тот же altGroupMain с маркером st.mrkId.
_FEED_HREF_RE = re.compile(r'href="([^"]+)"')


class OkApiClient:
    """Тонкий синхронный клиент OK API (REST, https://api.ok.ru/fb.do)."""

    def __init__(self, session: requests.Session | None = None) -> None:
        """Принимает HTTP-сессию, чтобы клиент было удобно мокать в тестах."""
        self._session = session or requests.Session()

    def _ensure_credentials(self) -> tuple[str, str, str]:
        """Возвращает (application_key, application_secret_key, access_token)."""

        application_key = settings.OK_APPLICATION_KEY
        secret_key = settings.OK_APPLICATION_SECRET_KEY
        access_token = settings.OK_ACCESS_TOKEN
        if application_key and secret_key and access_token:
            return application_key, secret_key, access_token

        raise OkApiError(
            "Интеграция с OK не настроена. Заполните OK_APPLICATION_KEY, "
            "OK_APPLICATION_SECRET_KEY и OK_ACCESS_TOKEN в .env"
        )

    def _build_sig(self, params: dict[str, Any], secret_key: str, access_token: str) -> str:
        """Считает подпись запроса по схеме OK.

        session_secret_key = md5(access_token + application_secret_key);
        sig = md5(конкатенация "k=v" по отсортированным ключам + session_secret_key).
        access_token в подпись не входит.
        """

        session_secret_key = (
            hashlib.md5(f"{access_token}{secret_key}".encode("utf-8")).hexdigest().lower()
        )
        signature_params = {
            key: value
            for key, value in params.items()
            if key != "access_token" and value is not None
        }
        signature_base = "".join(
            f"{key}={signature_params[key]}" for key in sorted(signature_params)
        )
        return (
            hashlib.md5(f"{signature_base}{session_secret_key}".encode("utf-8"))
            .hexdigest()
            .lower()
        )

    def call(self, method: str, params: dict[str, Any]) -> Any:
        """Вызывает метод OK API с retry для сетевых и сервисных ошибок."""

        application_key, secret_key, access_token = self._ensure_credentials()

        payload: dict[str, Any] = {
            "method": method,
            "application_key": application_key,
            "format": "json",
            "access_token": access_token,
            **{key: value for key, value in params.items() if value is not None},
        }
        payload["sig"] = self._build_sig(payload, secret_key, access_token)

        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.post(API_BASE, data=payload, timeout=20)
                data = resp.json()
            except (requests.exceptions.RequestException, ValueError) as exc:
                last_err = exc
                time.sleep(RETRY_DELAY_SEC)
                continue

            if isinstance(data, dict) and "error_code" in data:
                code = data.get("error_code")
                msg = data.get("error_msg", "OK API error")
                if code == OK_SERVICE_ERROR_CODE and attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY_SEC * (attempt + 1))
                    continue
                raise OkApiError(f"{method}: {msg}", code=code)

            time.sleep(getattr(settings, "OK_INTER_REQUEST_DELAY", INTER_REQUEST_DELAY_SEC))
            return data

        raise OkApiError(
            f"{method}: сеть не ответила после {MAX_RETRIES} попыток ({last_err})"
        )

    def get_group(self, group_ref: str) -> dict[str, Any]:
        """Возвращает данные группы через group.getInfo."""

        response = self.call("group.getInfo", {"uids": str(group_ref), "fields": OK_GROUP_FIELDS})
        items = response if isinstance(response, list) else []
        if not items:
            raise OkApiError(f"group.getInfo: группа '{group_ref}' не найдена", code=404)
        return items[0]

    def get_stat_topics(
        self,
        gid: str,
        *,
        count: int = TOPICS_PAGE_SIZE,
        anchor: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> dict[str, Any]:
        """Возвращает страницу group.getStatTopics.

        Метод статистики: работает, только если токен принадлежит
        администратору группы, а у приложения есть VALUABLE_ACCESS.
        """

        response = self.call(
            "group.getStatTopics",
            {
                "gid": gid,
                "fields": OK_STAT_TOPIC_FIELDS,
                "count": min(count, TOPICS_PAGE_SIZE),
                "anchor": anchor,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        return response if isinstance(response, dict) else {}

    def fetch_all_stat_topics(
        self,
        gid: str,
        *,
        max_topics: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
    ) -> list[dict[str, Any]]:
        """Тянет темы группы со статистикой.

        ``max_topics=None`` — без лимита. ``date_from``/``date_to`` фильтруют по
        ``created_ms`` (включительно). Границы периода также передаются в OK,
        чтобы не выкачивать лишние страницы.

        ``on_progress(собрано, ожидаемый_итог)`` вызывается после каждой
        страницы — даёт прогресс и точку прерывания (исключение из колбэка
        пробрасывается наружу).
        """

        ms_from = int(date_from.timestamp() * 1000) if date_from else None
        ms_to = int(date_to.timestamp() * 1000) if date_to else None

        collected: list[dict[str, Any]] = []
        anchor: str | None = None
        seen_anchors: set[str] = set()
        while max_topics is None or len(collected) < max_topics:
            count = (
                TOPICS_PAGE_SIZE
                if max_topics is None
                else min(TOPICS_PAGE_SIZE, max_topics - len(collected))
            )
            chunk = self.get_stat_topics(
                gid,
                count=count,
                anchor=anchor,
                start_time=ms_from,
                end_time=ms_to,
            )
            items = chunk.get("topics") or []
            if not items:
                break

            total = chunk.get("totalCount") or None
            for item in items:
                created_ms = item.get("created_ms")
                if created_ms is not None:
                    if ms_from is not None and created_ms < ms_from:
                        continue
                    if ms_to is not None and created_ms > ms_to:
                        continue
                collected.append(item)
                if max_topics is not None and len(collected) >= max_topics:
                    break

            if on_progress is not None:
                expected = min(max_topics, total) if (max_topics and total) else (total or max_topics)
                on_progress(len(collected), expected)

            anchor = chunk.get("anchor")
            if not chunk.get("has_more") or not anchor:
                break
            # Страховка от зацикливания: OK иногда отдаёт has_more=true с тем же
            # anchor — без этой проверки пагинация крутилась бы вечно.
            if anchor in seen_anchors:
                break
            seen_anchors.add(anchor)

        return collected if max_topics is None else collected[:max_topics]

    def fetch_public_topic_ids(
        self,
        group_id: str,
        *,
        shortname: str | None = None,
        max_topics: int | None = None,
        on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
    ) -> list[str]:
        """Собирает id тем группы из публичной мобильной версии m.ok.ru.

        Фолбэк для токенов без прав администратора: group.getStatTopics им
        недоступен (GROUP_RESTRICTION), а публичная лента открыта анонимно.
        Пагинация — по ссылке «Ещё» с маркером ``st.mrkId``. Темы идут
        свежие → старые. Порядок сохраняется, дубли (закреп) отбрасываются.
        """

        # Темы в ленте ссылаются и как /group/<uid>/topic/, и как
        # /<shortname>/topic/. Матчим только свою группу, чтобы не зацепить
        # чужие темы из рекомендательных блоков.
        prefixes = [re.escape(f"/group/{group_id}")]
        if shortname:
            prefixes.append(re.escape(f"/{shortname}"))
        topic_re = re.compile(rf"(?:{'|'.join(prefixes)})/topic/(\d+)")

        headers = {"User-Agent": OK_MOBILE_USER_AGENT, "Accept-Language": "ru"}
        url = f"{OK_MOBILE_BASE}/group/{group_id}"

        collected: list[str] = []
        seen: set[str] = set()
        for _page in range(OK_MOBILE_MAX_PAGES):
            try:
                resp = self._session.get(url, headers=headers, timeout=20)
            except requests.exceptions.RequestException as exc:
                if collected:
                    logger.warning("OK public feed pagination stopped: %s", exc)
                    break
                raise OkApiError(f"публичная лента группы недоступна: {exc}") from exc
            if resp.status_code >= 400:
                if collected:
                    logger.warning(
                        "OK public feed pagination stopped: HTTP %s", resp.status_code
                    )
                    break
                raise OkApiError(
                    f"публичная лента группы недоступна (HTTP {resp.status_code})"
                )

            page_html = resp.text
            new_ids = 0
            for topic_id in topic_re.findall(page_html):
                if topic_id in seen:
                    continue
                seen.add(topic_id)
                collected.append(topic_id)
                new_ids += 1
                if max_topics is not None and len(collected) >= max_topics:
                    break

            if on_progress is not None:
                on_progress(len(collected), None)
            if max_topics is not None and len(collected) >= max_topics:
                break
            # Ни одной новой темы — лента кончилась либо OK крутит нас по кругу.
            if new_ids == 0:
                break

            next_link = self._find_feed_more_link(page_html)
            if not next_link:
                break
            url = OK_MOBILE_BASE + next_link
            time.sleep(getattr(settings, "OK_INTER_REQUEST_DELAY", INTER_REQUEST_DELAY_SEC))

        return collected if max_topics is None else collected[:max_topics]

    @staticmethod
    def _find_feed_more_link(page_html: str) -> str | None:
        """Достаёт ссылку «Ещё» (следующая порция ленты) из HTML."""

        for href in _FEED_HREF_RE.findall(page_html):
            if "st.mrkId=" in href and "st.cmd=altGroupMain" in href:
                return html_lib.unescape(href)
        return None

    def get_mediatopics(self, topic_ids: list[str]) -> list[dict[str, Any]]:
        """Возвращает содержимое тем через mediatopic.getByIds (батчами)."""

        result: list[dict[str, Any]] = []
        for start in range(0, len(topic_ids), MEDIATOPIC_BATCH_SIZE):
            batch = topic_ids[start : start + MEDIATOPIC_BATCH_SIZE]
            response = self.call(
                "mediatopic.getByIds",
                {
                    "topic_ids": ",".join(batch),
                    "fields": OK_MEDIATOPIC_FIELDS,
                    # Обязателен при запросе нескольких медиатопиков (1..3).
                    "media_limit": 3,
                },
            )
            if isinstance(response, dict):
                items = response.get("media_topics") or response.get("entities", {}).get(
                    "mediatopics", []
                )
            else:
                items = response or []
            result.extend(items)
        return result

    def get_discussion_comments(
        self,
        topic_id: str,
        *,
        count: int = COMMENTS_PAGE_SIZE,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Возвращает страницу комментариев темы группы."""

        response = self.call(
            "discussions.getDiscussionComments",
            {
                "entityId": topic_id,
                "entityType": GROUP_TOPIC_DISCUSSION_TYPE,
                "count": min(count, COMMENTS_PAGE_SIZE),
                "offset": offset,
            },
        )
        return response if isinstance(response, dict) else {}

    def fetch_all_comments(self, topic_id: str, *, max_comments: int = 500) -> list[dict[str, Any]]:
        """Тянет до max_comments комментариев темы."""

        collected: list[dict[str, Any]] = []
        offset = 0
        while len(collected) < max_comments:
            requested = min(COMMENTS_PAGE_SIZE, max_comments - len(collected))
            chunk = self.get_discussion_comments(topic_id, count=requested, offset=offset)
            # В схеме OK ключ описан как "commentss"; на практике приходит
            # "comments". Читаем оба, чтобы не зависеть от расхождения.
            items = chunk.get("comments") or chunk.get("commentss") or []
            if not items:
                break
            collected.extend(items)
            offset += len(items)
            total = chunk.get("total_count") or chunk.get("totalCount")
            if total is not None and offset >= total:
                break
            # Неполная страница — данные кончились. Заодно страхует от OK,
            # который проигнорировал offset и вернул ту же страницу снова.
            if len(items) < requested:
                break
        return collected[:max_comments]
