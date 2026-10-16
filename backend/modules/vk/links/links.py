"""Распознавание трёх типов VK-ссылок: сообщество, профиль, конкретный пост."""

from __future__ import annotations

import re

from backend.modules.vk.dto.dto import VkLinkRef, VkLinkType
from backend.modules.vk.utils.constants import RESERVED_PATHS
from backend.modules.vk.utils.errors import InvalidVkLinkError



# vk.ru — официальный зеркальный домен VK, ссылки оттуда приходят наравне с
# vk.com, поэтому распознаём оба. Канонизируем всё равно в vk.com.
_VK_HOSTS = ("vk.com", "vk.ru")

# Каноничный маркер пути на vk.com / vk.ru.
_HOST_RE = re.compile(
    r"^(?:https?://)?(?:m\.|www\.)?vk\.(?:com|ru)/", re.IGNORECASE
)

# wall<owner>_<post> в любой части URL (поддерживаются и /wall-123_456, и ?w=wall-123_456).
_WALL_RE = re.compile(r"wall(-?\d+)_(\d+)", re.IGNORECASE)

# club123 / public123 / event123 — числовое сообщество.
_NUMERIC_GROUP_RE = re.compile(r"^(?:club|public|event)(\d+)$", re.IGNORECASE)

# id123 — числовой профиль.
_NUMERIC_USER_RE = re.compile(r"^id(\d+)$", re.IGNORECASE)

# Допустимый screen_name: латиница / цифры / _ / .
_SCREEN_NAME_RE = re.compile(r"^[A-Za-z0-9_.]{1,64}$")


def _strip_host(raw: str) -> tuple[str, bool]:
    """Снимает протокол и хост vk.com. Возвращает (path_or_screen, is_url)"""

    text = raw.strip()
    if not text:
        return "", False

    lowered = text.lower()
    is_url = any(host in lowered for host in _VK_HOSTS) or "://" in text or text.startswith("/")
    text = _HOST_RE.sub("", text, count=1)
    text = text.strip().lstrip("/")
    return text, is_url


def _split_path_query(path: str) -> tuple[str, dict[str, str]]:
    if "?" not in path:
        return path, {}
    base, _, query = path.partition("?")
    qs: dict[str, str] = {}
    for pair in query.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        qs[key.lower()] = value
    return base, qs


def parse_vk_link(raw: str) -> VkLinkRef:
    """Распознать VK-ссылку как community / profile / post."""

    if raw is None:
        raise InvalidVkLinkError("VK-ссылка не передана")

    raw = raw.strip()
    if not raw:
        raise InvalidVkLinkError("VK-ссылка пустая")

    text, is_url = _strip_host(raw)
    if not text:
        raise InvalidVkLinkError("Не удаётся распознать VK-ссылку")

    base, qs = _split_path_query(text)
    base = base.rstrip("/")

    # Сценарий 1. Прямая ссылка вида wall-123_456 в пути или /<screen>?w=wall...
    wall_match = _WALL_RE.search(base) or _WALL_RE.search(qs.get("w", ""))
    if wall_match:
        owner_id = int(wall_match.group(1))
        post_id = int(wall_match.group(2))
        canonical = f"https://vk.com/wall{owner_id}_{post_id}"
        return VkLinkRef(
            type=VkLinkType.POST,
            raw_url=raw,
            canonical_url=canonical,
            owner_id=owner_id,
            post_id=post_id,
        )

    # Дальше в base должно остаться что-то вроде screen_name или numeric id.
    # Берём первый сегмент.
    screen = base.split("/", 1)[0]
    if not screen:
        raise InvalidVkLinkError("Не удаётся распознать путь VK-ссылки")

    screen_lower = screen.lower()

    if screen_lower in RESERVED_PATHS:
        raise InvalidVkLinkError(
            f"'{screen}' — служебная страница VK, импорт не поддерживается"
        )

    # club123 / public123 / event123 → community с owner_id = -N
    numeric_group = _NUMERIC_GROUP_RE.match(screen)
    if numeric_group:
        gid = int(numeric_group.group(1))
        return VkLinkRef(
            type=VkLinkType.COMMUNITY,
            raw_url=raw,
            canonical_url=f"https://vk.com/{screen_lower}",
            owner_id=-gid,
            screen_name=screen_lower,
        )

    # id123 → profile с owner_id = +N
    numeric_user = _NUMERIC_USER_RE.match(screen)
    if numeric_user:
        uid = int(numeric_user.group(1))
        return VkLinkRef(
            type=VkLinkType.PROFILE,
            raw_url=raw,
            canonical_url=f"https://vk.com/{screen_lower}",
            owner_id=uid,
            screen_name=screen_lower,
        )

    # screen_name — символ строки. Тип определяется только на этапе resolve через VK API
    # (utils.resolveScreenName), но мы ставим COMMUNITY как наиболее вероятный сценарий
    # для входов вида vk.com/mkotyukov. Финальное уточнение делает сервис ингеста.
    if not _SCREEN_NAME_RE.match(screen):
        raise InvalidVkLinkError(
            "Короткое имя VK может содержать только латиницу, цифры, '_' и '.'"
        )

    return VkLinkRef(
        type=VkLinkType.COMMUNITY,
        raw_url=raw,
        canonical_url=f"https://vk.com/{screen}",
        domain=screen,
        screen_name=screen,
    )
