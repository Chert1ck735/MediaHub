"""Классовый VK API-клиент.

Содержит только HTTP-вызовы VK и пагинацию VK API.
Не знает про FastAPI, SQLAlchemy и бизнес-логику приложения.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Callable, Optional

import requests

from backend.app.config import settings
from backend.modules.vk.utils.constants import VK_USER_FIELDS, VK_GROUP_FIELDS, MAX_RETRIES, INTER_REQUEST_DELAY_SEC, \
    RETRY_DELAY_SEC, API_BASE
from backend.modules.vk.utils.errors import VkApiError

logger = logging.getLogger(__name__)


class VkApiClient:
    """Тонкий синхронный клиент VK API."""

    def __init__(self, session: requests.Session | None = None) -> None:
        """Принимает HTTP-сессию, чтобы клиент было удобно мокать в тестах."""
        self._session = session or requests.Session()

    def _ensure_token(self) -> str:
        """Возвращает VK access token или выбрасывает доменную ошибку."""

        token = settings.ACCESS_TOKEN
        if not token or token == "init-db-placeholder":
            raise VkApiError(
                "VK ACCESS_TOKEN не задан. Заполните ACCESS_TOKEN в .env "
                "(сервисный токен сообщества или пользовательский с правом wall)"
            )
        return token

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Вызывает метод VK API с retry для сетевых ошибок и rate limit."""

        token = self._ensure_token()
        full = {**params, "v": settings.VK_API_VERSION, "access_token": token}
        url = f"{API_BASE}/{method}"

        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.get(url, params=full, timeout=15)
                data = resp.json()
            except (requests.exceptions.RequestException, ValueError) as exc:
                last_err = exc
                time.sleep(RETRY_DELAY_SEC)
                continue

            if "error" in data:
                err = data["error"]
                code = err.get("error_code")
                msg = err.get("error_msg", "VK API error")
                if code == 6 and attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY_SEC * (attempt + 1))
                    continue
                raise VkApiError(f"{method}: {msg}", code=code)

            time.sleep(getattr(settings, "VK_INTER_REQUEST_DELAY", INTER_REQUEST_DELAY_SEC))
            return data["response"]

        raise VkApiError(
            f"{method}: сеть не ответила после {MAX_RETRIES} попыток ({last_err})"
        )

    def resolve_screen_name(self, screen_name: str) -> dict[str, Any]:
        """Возвращает результат utils.resolveScreenName."""

        return self.call("utils.resolveScreenName", {"screen_name": screen_name}) or {}

    def get_group(self, group_ref: str | int) -> dict[str, Any]:
        """Возвращает расширенные поля сообщества."""

        params: dict[str, Any] = {"fields": VK_GROUP_FIELDS}
        if isinstance(group_ref, int):
            params["group_id"] = abs(group_ref)
        else:
            params["group_ids"] = str(group_ref)
        response = self.call("groups.getById", params)
        items = response["groups"] if isinstance(response, dict) and "groups" in response else response or []
        if not items:
            raise VkApiError(f"groups.getById: сообщество '{group_ref}' не найдено", code=125)
        return items[0]

    def get_user(self, user_id: int | str) -> dict[str, Any]:
        """Возвращает базовые поля профиля."""

        response = self.call(
            "users.get",
            {"user_ids": str(user_id), "fields": VK_USER_FIELDS},
        )
        if not response:
            raise VkApiError(f"users.get: профиль '{user_id}' не найден", code=104)
        return response[0]

    def get_user_followers_count(self, user_id: int | str) -> int:
        """Число подписчиков профиля через users.getFollowers."""

        response = self.call("users.getFollowers", {"user_id": int(user_id), "count": 0})
        if isinstance(response, dict):
            return int(response.get("count") or 0)
        return 0

    def wall_get(self, *, owner_id: Optional[int] = None, domain: Optional[str] = None, count: int = 20, offset: int = 0, extended: int = 0) -> dict[str, Any]:
        """Возвращает страницу wall.get."""

        params: dict[str, Any] = {"count": min(count, 100), "offset": offset, "extended": extended}
        if owner_id is not None:
            params["owner_id"] = owner_id
        if domain is not None:
            params["domain"] = domain
        return self.call("wall.get", params)

    def wall_get_by_id(self, owner_id: int, post_id: int) -> dict[str, Any]:
        """Возвращает один пост через wall.getById."""

        response = self.call("wall.getById", {"posts": f"{owner_id}_{post_id}"})
        if not response:
            raise VkApiError(f"wall.getById: пост {owner_id}_{post_id} не найден", code=104)
        if isinstance(response, dict) and "items" in response:
            items = response["items"]
            if not items:
                raise VkApiError(f"wall.getById: пост {owner_id}_{post_id} не найден", code=104)
            return items[0]
        return response[0]

    def wall_get_comments(
            self,
            owner_id: int,
            post_id: int,
            *,
            count: int = 100,
            offset: int = 0,
            thread_items_count: int = 10
    ) -> dict[str, Any]:
        """Возвращает страницу комментариев wall.getComments."""

        return self.call(
            "wall.getComments",
            {
                "owner_id": owner_id,
                "post_id": post_id,
                "count": min(count, 100),
                "offset": offset,
                "thread_items_count": thread_items_count,
                "need_likes": 1,
                "extended": 0,
            },
        )

    def fetch_all_wall(
            self,
            *,
            owner_id: Optional[int] = None,
            domain: Optional[str] = None,
            max_posts: Optional[int] = 100,
            date_from: Optional[datetime] = None,
            date_to: Optional[datetime] = None,
            on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
    ) -> list[dict[str, Any]]:
        """Тянет посты со стены.

        max_posts=None — без лимита (вся стена). date_from/date_to ограничивают
        период по дате поста (включительно). Посты идут свежие→старые, поэтому
        дойдя до поста старше date_from, пагинацию останавливаем (закреплённые
        посты не учитываем в условии остановки).

        on_progress(собрано, ожидаемый_итог) вызывается после каждой страницы:
        даёт прогресс на долгой пагинации и точку, где вызывающий может прервать
        загрузку (исключение из колбэка пробрасывается наружу).
        """

        ts_from = int(date_from.timestamp()) if date_from else None
        ts_to = int(date_to.timestamp()) if date_to else None

        collected: list[dict[str, Any]] = []
        offset = 0
        page_size = 100
        stop = False
        while max_posts is None or len(collected) < max_posts:
            count = page_size if max_posts is None else min(page_size, max_posts - len(collected))
            chunk = self.wall_get(
                owner_id=owner_id,
                domain=domain,
                count=count,
                offset=offset,
            )
            items = chunk.get("items", [])
            total = chunk.get("count", 0)
            if not items:
                break

            for item in items:
                post_date = item.get("date")
                if ts_from is not None and post_date is not None and post_date < ts_from:
                    if not item.get("is_pinned"):
                        stop = True
                        break
                    continue
                if ts_to is not None and post_date is not None and post_date > ts_to:
                    continue
                collected.append(item)
                if max_posts is not None and len(collected) >= max_posts:
                    break

            offset += len(items)
            if on_progress is not None:
                if max_posts is not None:
                    expected = min(max_posts, total) if total else max_posts
                else:
                    expected = total or None
                on_progress(len(collected), expected)
            if stop or offset >= total:
                break

        return collected if max_posts is None else collected[:max_posts]

    def fetch_all_comments(
        self, owner_id: int, post_id: int, *, max_comments: int | None = None
    ) -> list[dict[str, Any]]:
        """Тянет комментарии вместе с полными ветками ответов.

        max_comments=None — без лимита (весь пост). ВК прикладывает к ветке максимум
        10 ответов (thread_items_count), более длинные докачиваем отдельными запросами.
        """

        collected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        offset = 0
        page_size = 100

        def append_unique(raw: dict[str, Any]) -> None:
            comment_id = raw.get("id")
            key = str(comment_id) if comment_id is not None else ""
            if not key or key in seen_ids:
                return
            seen_ids.add(key)
            collected.append(raw)

        def limit_reached() -> bool:
            return max_comments is not None and len(collected) >= max_comments

        while not limit_reached():
            chunk = self.wall_get_comments(
                owner_id=owner_id,
                post_id=post_id,
                count=page_size,
                offset=offset,
            )
            items = chunk.get("items", [])
            total = chunk.get("count", 0)
            if not items:
                break
            for item in items:
                append_unique(item)
                thread = item.get("thread", {}) or {}
                thread_items = thread.get("items", []) or []
                for thread_item in thread_items:
                    append_unique(thread_item)
                # ВК приложил не всю ветку — докачиваем по comment_id
                if int(thread.get("count") or 0) > len(thread_items) and not limit_reached():
                    for reply in self._fetch_thread(owner_id, post_id, item.get("id")):
                        append_unique(reply)
            offset += len(items)
            if offset >= total:
                break
        return collected if max_comments is None else collected[:max_comments]

    def _fetch_thread(self, owner_id: int, post_id: int, comment_id: int | None) -> list[dict[str, Any]]:
        """Полная ветка ответов на комментарий (wall.getComments с comment_id)."""
        if not comment_id:
            return []
        replies: list[dict[str, Any]] = []
        offset = 0
        while True:
            chunk = self.call("wall.getComments", {
                "owner_id": owner_id,
                "post_id": post_id,
                "comment_id": comment_id,
                "count": 100,
                "offset": offset,
                "need_likes": 1,
                "extended": 0,
            })
            items = chunk.get("items", [])
            if not items:
                break
            replies.extend(items)
            offset += len(items)
            if offset >= int(chunk.get("count") or 0):
                break
        return replies


_default_client = VkApiClient()


def resolve_screen_name(screen_name: str) -> dict[str, Any]:
    """Backward-compatible wrapper для старого импорта."""

    return _default_client.resolve_screen_name(screen_name)


def get_group(group_ref: str | int) -> dict[str, Any]:
    """Backward-compatible wrapper для старого импорта."""

    return _default_client.get_group(group_ref)


def get_user(user_id: int | str) -> dict[str, Any]:
    """Backward-compatible wrapper для старого импорта."""

    return _default_client.get_user(user_id)


def get_user_followers_count(user_id: int | str) -> int:
    """Обёртка над users.getFollowers, оставленная для совместимости."""

    return _default_client.get_user_followers_count(user_id)


def fetch_all_wall(*, owner_id: Optional[int] = None, domain: Optional[str] = None, max_posts: int = 100) -> list[dict[str, Any]]:
    """Backward-compatible wrapper для старого импорта."""

    return _default_client.fetch_all_wall(owner_id=owner_id, domain=domain, max_posts=max_posts)


def fetch_all_comments(owner_id: int, post_id: int, *, max_comments: int = 500) -> list[dict[str, Any]]:
    """Backward-compatible wrapper для старого импорта."""

    return _default_client.fetch_all_comments(owner_id, post_id, max_comments=max_comments)


def wall_get_by_id(owner_id: int, post_id: int) -> dict[str, Any]:
    """Backward-compatible wrapper для старого импорта."""

    return _default_client.wall_get_by_id(owner_id, post_id)
