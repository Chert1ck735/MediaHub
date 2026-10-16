"""Распознавание ссылок Одноклассников: группа, профиль, тема (пост)."""

from __future__ import annotations

import re

from backend.modules.ok.dto.dto import OkLinkRef, OkLinkType
from backend.modules.ok.utils.constants import RESERVED_PATHS
from backend.modules.ok.utils.errors import InvalidOkLinkError

# Хост ok.ru / odnoklassniki.ru с мобильным и www-префиксом.
_HOST_RE = re.compile(
    r"^(?:https?://)?(?:m\.|www\.)?(?:ok\.ru|odnoklassniki\.ru)/",
    re.IGNORECASE,
)

# Числовой идентификатор группы/профиля OK.
_NUMERIC_RE = re.compile(r"^\d+$")

# Допустимый shortname OK: латиница / цифры / _ / . / -
_SHORTNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _strip_host(raw: str) -> str:
    """Снимает протокол и хост ok.ru, возвращает путь."""

    text = raw.strip()
    if not text:
        return ""

    text = _HOST_RE.sub("", text, count=1)
    return text.strip().lstrip("/")


def _strip_query(path: str) -> str:
    """Отбрасывает query и fragment — в OK-ссылках они только служебные (?st.*)."""

    return path.partition("?")[0].partition("#")[0]


def _segments(path: str) -> list[str]:
    """Разбивает путь на непустые сегменты."""

    return [segment for segment in path.split("/") if segment]


def _validate_ref(value: str, *, what: str) -> str:
    """Проверяет, что идентификатор — число или корректный shortname."""

    if _NUMERIC_RE.match(value) or _SHORTNAME_RE.match(value):
        return value
    raise InvalidOkLinkError(
        f"{what} OK может содержать только латиницу, цифры, '_', '.' и '-'"
    )


def _topic_ref(group_ref: str | None, topic_id: str) -> OkLinkRef:
    """Собирает ссылку на тему группы."""

    canonical = (
        f"https://ok.ru/group/{group_ref}/topic/{topic_id}"
        if group_ref
        else f"https://ok.ru/topic/{topic_id}"
    )
    return OkLinkRef(
        type=OkLinkType.TOPIC,
        raw_url=canonical,
        canonical_url=canonical,
        group_ref=group_ref,
        topic_id=topic_id,
    )


def parse_ok_link(raw: str) -> OkLinkRef:
    """Распознать ссылку Одноклассников как group / profile / topic.

    Поддерживаются формы:
    ``ok.ru/group/<uid|shortname>``, ``ok.ru/group/<...>/topic/<id>``,
    ``ok.ru/topic/<id>``, ``ok.ru/profile/<uid|nick>`` и голый
    ``ok.ru/<shortname>`` (трактуется как группа).
    """

    if raw is None:
        raise InvalidOkLinkError("OK-ссылка не передана")

    raw = raw.strip()
    if not raw:
        raise InvalidOkLinkError("OK-ссылка пустая")

    path = _strip_query(_strip_host(raw))
    parts = _segments(path)
    if not parts:
        raise InvalidOkLinkError("Не удаётся распознать OK-ссылку")

    head = parts[0].lower()

    # ok.ru/group/<ref>[/topic/<id>]
    if head == "group":
        if len(parts) < 2:
            raise InvalidOkLinkError("В OK-ссылке не указан идентификатор группы")
        group_ref = _validate_ref(parts[1], what="Идентификатор группы")

        if len(parts) >= 4 and parts[2].lower() == "topic":
            topic_id = parts[3]
            if not _NUMERIC_RE.match(topic_id):
                raise InvalidOkLinkError("Идентификатор темы OK должен быть числом")
            return _topic_ref(group_ref, topic_id)

        canonical = f"https://ok.ru/group/{group_ref}"
        return OkLinkRef(
            type=OkLinkType.GROUP,
            raw_url=raw,
            canonical_url=canonical,
            group_ref=group_ref,
            group_id=group_ref if _NUMERIC_RE.match(group_ref) else None,
        )

    # ok.ru/topic/<id> — тема без указания группы, владельца достанем из API.
    if head == "topic":
        if len(parts) < 2 or not _NUMERIC_RE.match(parts[1]):
            raise InvalidOkLinkError("Идентификатор темы OK должен быть числом")
        return _topic_ref(None, parts[1])

    # ok.ru/profile/<ref>
    if head == "profile":
        if len(parts) < 2:
            raise InvalidOkLinkError("В OK-ссылке не указан идентификатор профиля")
        profile_ref = _validate_ref(parts[1], what="Идентификатор профиля")
        return OkLinkRef(
            type=OkLinkType.PROFILE,
            raw_url=raw,
            canonical_url=f"https://ok.ru/profile/{profile_ref}",
            profile_ref=profile_ref,
        )

    if head in RESERVED_PATHS:
        raise InvalidOkLinkError(
            f"'{parts[0]}' — служебная страница OK, импорт не поддерживается"
        )

    # ok.ru/<shortname> — почти всегда короткое имя группы. Числовой id без
    # префикса неоднозначен (группа или профиль), поэтому такое не принимаем.
    if _NUMERIC_RE.match(head):
        raise InvalidOkLinkError(
            "Числовой id без раздела неоднозначен. "
            "Укажите ok.ru/group/<id> или ok.ru/profile/<id>"
        )

    shortname = _validate_ref(parts[0], what="Короткое имя")
    return OkLinkRef(
        type=OkLinkType.GROUP,
        raw_url=raw,
        canonical_url=f"https://ok.ru/group/{shortname}",
        group_ref=shortname,
    )
