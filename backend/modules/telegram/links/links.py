"""Чистый разбор ссылок публичных Telegram-каналов."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from backend.modules.telegram.errors import InvalidTelegramLinkError

_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_HOSTS = {"t.me", "telegram.me"}


@dataclass(frozen=True)
class TelegramLinkRef:
    """Нормализованная ссылка на публичный канал или конкретный его пост."""

    raw_url: str
    username: str
    canonical_url: str
    post_id: int | None = None


def parse_telegram_link(raw: str) -> TelegramLinkRef:
    """Принимает t.me/<channel> и t.me/<channel>/<post_id>.

    Инвайт-ссылки, private ``c/`` URL и ссылки на ботов намеренно не
    поддерживаем: сервис импорта не должен пытаться вступать в закрытые чаты.
    """

    value = (raw or "").strip()
    if not value:
        raise InvalidTelegramLinkError("Укажите ссылку Telegram-канала")
    if value.startswith("@"):
        value = f"https://t.me/{value[1:]}"
    if "://" not in value:
        value = f"https://{value}"

    parts = urlsplit(value)
    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    if parts.scheme not in {"http", "https"} or host not in _HOSTS:
        raise InvalidTelegramLinkError("Поддерживаются публичные ссылки вида t.me/<канал>")

    segments = [item for item in parts.path.split("/") if item]
    if segments[:1] == ["s"]:
        segments = segments[1:]
    if len(segments) not in {1, 2} or not _USERNAME_RE.fullmatch(segments[0]):
        raise InvalidTelegramLinkError(
            "Укажите публичный канал: t.me/<канал> или ссылку на его пост"
        )

    post_id: int | None = None
    if len(segments) == 2:
        if not segments[1].isdigit() or int(segments[1]) < 1:
            raise InvalidTelegramLinkError("Номер поста Telegram должен быть положительным числом")
        post_id = int(segments[1])

    username = segments[0]
    return TelegramLinkRef(
        raw_url=raw,
        username=username,
        canonical_url=f"https://t.me/{username}",
        post_id=post_id,
    )

