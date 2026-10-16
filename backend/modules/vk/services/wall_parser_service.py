"""Сервис чтения стены VK и экспорта постов."""

import csv
import re
import time
from pathlib import Path
from typing import Optional

import requests

from backend.app.config import settings
from backend.modules.vk.dto.dto import ParsedVkPostDTO, FetchPostsResultDTO
from backend.modules.vk.dto.post_mapper import VkPostMapper
from backend.modules.vk.utils.constants import POSTING_MAX_RETRIES, POSTING_RETRY_DELAY_SEC, INTER_REQUEST_DELAY_SEC, \
    VK_INVALID_TARGET_ERROR_CODES, RESERVED_PATHS
from backend.modules.vk.utils.errors import VKAPIError, InvalidVKUrlError

_VK_DOMAIN_RE = re.compile(r"^[A-Za-z0-9_.]{1,64}$")
_VK_URL_RE = re.compile(r"^(?:https?://)?(?:m\.|www\.)?vk\.(?:com|ru)/(?P<path>[A-Za-z0-9_.]+)/?$", re.IGNORECASE)
_NUMERIC_ID_RE = re.compile(r"^(?:club|public)(?P<id>\d+)$", re.IGNORECASE)

class VkWallParserService:
    """Сервис старого сценария /parse: чтение стены сообщества и CSV."""

    def __init__(self, mapper: VkPostMapper | None = None, session: requests.Session | None = None) -> None:
        self._mapper = mapper or VkPostMapper()
        self._session = session or requests.Session()

    def parse_vk_community_ref(self, url_or_domain: str) -> dict:
        """Превращает ссылку/идентификатор сообщества VK в параметры wall.get."""

        if url_or_domain is None:
            raise InvalidVKUrlError("Ссылка на сообщество VK не передана")
        raw = url_or_domain.strip()
        if not raw:
            raise InvalidVKUrlError("Ссылка на сообщество VK не может быть пустой")
        raw_lower = raw.lower()
        looks_like_url = (
            "://" in raw
            or "/" in raw
            or raw_lower.startswith("vk.com")
            or raw_lower.startswith("vk.ru")
        )
        if looks_like_url:
            match = _VK_URL_RE.match(raw)
            if not match:
                raise InvalidVKUrlError("Ожидается ссылка вида https://vk.com/<сообщество>")
            path = match.group("path")
        else:
            path = raw
        path_lower = path.lower()
        if path_lower in RESERVED_PATHS:
            raise InvalidVKUrlError(f"'{path}' — служебная страница VK, а не сообщество")
        if re.fullmatch(r"id\d+", path_lower):
            raise InvalidVKUrlError("Это ссылка на личный профиль, а не на сообщество")
        numeric = _NUMERIC_ID_RE.match(path)
        if numeric:
            return {"owner_id": -int(numeric.group("id")), "domain_label": path}
        if not _VK_DOMAIN_RE.match(path):
            raise InvalidVKUrlError("Короткое имя сообщества может содержать только латиницу, цифры, '_' и '.'")
        return {"domain": path, "domain_label": path}

    def fetch_posts(self, url: str, max_posts: Optional[int] = None) -> FetchPostsResultDTO:
        """Собирает посты со стены сообщества VK."""

        ref = self.parse_vk_community_ref(url)
        domain_label = ref.pop("domain_label")
        limit = max_posts or settings.VK_PARSER_MAX_POSTS
        count = settings.VK_PARSER_COUNT_PER_REQUEST
        all_posts: list[dict] = []
        offset = 0
        while True:
            params = {**ref, "count": count, "offset": offset, "v": settings.VK_API_VERSION, "access_token": settings.ACCESS_TOKEN}
            data = self._get_with_retries(settings.VK_API_URL_GET, params)
            if "error" in data:
                err = data["error"]
                code = err.get("error_code")
                msg = err.get("error_msg", "VK API error")
                if code in VK_INVALID_TARGET_ERROR_CODES:
                    raise InvalidVKUrlError(f"Сообщество '{domain_label}' недоступно: {msg}")
                raise VKAPIError(msg)
            items = data["response"]["items"]
            total = data["response"]["count"]
            if not items:
                break
            all_posts.extend(items)
            offset += count
            if len(all_posts) >= limit:
                all_posts = all_posts[:limit]
                break
            if offset >= total:
                break
            time.sleep(INTER_REQUEST_DELAY_SEC)
        return FetchPostsResultDTO(posts=all_posts, domain_label=domain_label)

    def parse_post(self, post: dict) -> ParsedVkPostDTO:
        """Извлекает интересующие поля из сырого VK-поста."""

        return self._mapper.to_parsed_dto(post)

    def save_posts_to_csv(self, posts: list[dict], filename: Optional[Path] = None) -> Path:
        """Сохраняет уже распарсенные посты в CSV."""

        path = Path(filename) if filename else settings.vk_parser_output_abs
        fieldnames = ["id", "date", "text", "likes", "reposts", "comments", "views"]
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            for post in posts:
                row = dict(post)
                if hasattr(row.get("date"), "strftime"):
                    row["date"] = row["date"].strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow(row)
        return path

    def _get_with_retries(self, url: str, params: dict) -> dict:
        """GET с retry."""

        last_err: Optional[Exception] = None
        for _ in range(POSTING_MAX_RETRIES):
            try:
                resp = self._session.get(url, params=params, timeout=15)
                return resp.json()
            except (requests.exceptions.RequestException, ValueError) as exc:
                last_err = exc
                time.sleep(POSTING_RETRY_DELAY_SEC)
        raise VKAPIError(f"VK GET {url} не ответил после {POSTING_MAX_RETRIES} попыток: {last_err}")


_default_service = VkWallParserService()


def parse_vk_community_ref(url_or_domain: str) -> dict:
    """Backward-compatible wrapper."""

    return _default_service.parse_vk_community_ref(url_or_domain)


def fetch_posts(url: str, max_posts: Optional[int] = None) -> tuple[list[dict], str]:
    """Backward-compatible wrapper."""

    result = _default_service.fetch_posts(url, max_posts)
    return result.posts, result.domain_label


def parse_post(post: dict) -> dict:
    """Backward-compatible wrapper."""

    return _default_service.parse_post(post).__dict__


def save_posts_to_csv(posts: list[dict], filename: Optional[Path] = None) -> Path:
    """Backward-compatible wrapper."""

    return _default_service.save_posts_to_csv(posts, filename)
