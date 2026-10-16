"""Тонкая обёртка Telethon с обязательной маршрутизацией через WPS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.app.config import Settings, settings
from backend.modules.telegram.errors import TelegramConfigurationError, TelegramIngestionError
from backend.modules.telegram.links.links import TelegramLinkRef


@dataclass(frozen=True)
class TelegramChannelDTO:
    id: str
    title: str
    username: str
    canonical_url: str
    members_count: int = 0


@dataclass(frozen=True)
class TelegramMessageDTO:
    id: int
    text: str
    published_at: datetime
    views: int = 0
    forwards: int = 0
    comments_count: int = 0
    content_type: str = "text"


@dataclass(frozen=True)
class TelegramCommentDTO:
    id: int
    text: str
    author_id: str | None
    author_name: str | None
    published_at: datetime | None
    parent_id: int | None = None


@dataclass
class TelegramFetchResult:
    channel: TelegramChannelDTO
    messages: list[TelegramMessageDTO] = field(default_factory=list)
    comments: dict[int, list[TelegramCommentDTO]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class TelegramApiClient:
    """Читает публичный канал за одно MTProto-подключение."""

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings

    def _validate_settings(self) -> None:
        missing = []
        if self.settings.TELEGRAM_API_ID <= 0:
            missing.append("TELEGRAM_API_ID")
        if not self.settings.TELEGRAM_API_HASH.strip():
            missing.append("TELEGRAM_API_HASH")
        if not self.settings.TELEGRAM_SESSION_STRING.strip():
            missing.append("TELEGRAM_SESSION_STRING")
        if missing:
            raise TelegramConfigurationError("Не заданы " + ", ".join(missing))
        if self.settings.TELEGRAM_PROXY_ENABLED:
            if not self.settings.TELEGRAM_PROXY_HOST.strip() or not self.settings.TELEGRAM_PROXY_SECRET.strip():
                raise TelegramConfigurationError(
                    "Для Telegram включён обязательный WPS-прокси: задайте "
                    "TELEGRAM_PROXY_HOST и TELEGRAM_PROXY_SECRET"
                )
            try:
                bytes.fromhex(self.settings.TELEGRAM_PROXY_SECRET.strip())
            except ValueError as exc:
                raise TelegramConfigurationError("TELEGRAM_PROXY_SECRET должен быть hex-секретом WPS") from exc

    async def fetch(
        self,
        ref: TelegramLinkRef,
        *,
        max_posts: int | None,
        date_from: datetime | None,
        date_to: datetime | None,
        fetch_comments: bool,
        reporter=None,
    ) -> TelegramFetchResult:
        self._validate_settings()
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyAbridged
            from telethon.tl.functions.channels import GetFullChannelRequest
        except ImportError as exc:  # pragma: no cover - защищает неполную установку
            raise TelegramConfigurationError("Не установлен пакет Telethon") from exc

        proxy: tuple[str, int, str] | None = None
        connection = None
        if self.settings.TELEGRAM_PROXY_ENABLED:
            proxy = (
                self.settings.TELEGRAM_PROXY_HOST.strip(),
                self.settings.TELEGRAM_PROXY_PORT,
                self.settings.TELEGRAM_PROXY_SECRET.strip(),
            )
            connection = ConnectionTcpMTProxyAbridged

        client = TelegramClient(
            StringSession(self.settings.TELEGRAM_SESSION_STRING.strip()),
            self.settings.TELEGRAM_API_ID,
            self.settings.TELEGRAM_API_HASH.strip(),
            connection=connection,
            proxy=proxy,
            receive_updates=False,
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramConfigurationError(
                    "TELEGRAM_SESSION_STRING не авторизована. Создайте новую StringSession "
                    "для пользовательского аккаунта Telegram."
                )
            entity = await client.get_entity(ref.username)
            full = await client(GetFullChannelRequest(entity))
            participants = int(getattr(full.full_chat, "participants_count", 0) or 0)
            title = str(getattr(entity, "title", "") or ref.username)
            username = str(getattr(entity, "username", "") or ref.username)
            result = TelegramFetchResult(
                channel=TelegramChannelDTO(
                    id=str(getattr(entity, "id", ref.username)),
                    title=title,
                    username=username,
                    canonical_url=f"https://t.me/{username}",
                    members_count=participants,
                )
            )

            if ref.post_id is not None:
                raw_messages = [await client.get_messages(entity, ids=ref.post_id)]
            else:
                limit = max_posts or self.settings.TELEGRAM_MAX_POSTS
                raw_messages = [item async for item in client.iter_messages(entity, limit=limit)]

            for index, message in enumerate(raw_messages, start=1):
                if message is None or getattr(message, "id", None) is None:
                    continue
                dto = self._message_dto(message)
                if not self._in_period(dto.published_at, date_from, date_to):
                    continue
                result.messages.append(dto)
                if reporter is not None and (index % 10 == 0 or index == len(raw_messages)):
                    await reporter.update(done=index, total=len(raw_messages), message="Загрузка постов Telegram…")

            if fetch_comments:
                for message in result.messages:
                    if not message.comments_count:
                        continue
                    try:
                        result.comments[message.id] = [
                            self._comment_dto(item)
                            async for item in client.iter_messages(entity, reply_to=message.id)
                            if (getattr(item, "message", "") or "").strip()
                        ]
                    except Exception as exc:  # один закрытый discussion не ломает весь импорт
                        result.notes.append(
                            f"Комментарии к посту {message.id} недоступны: {type(exc).__name__}"
                        )
            return result
        except TelegramConfigurationError:
            raise
        except Exception as exc:
            raise TelegramIngestionError(f"Telegram MTProto: {exc}") from exc
        finally:
            await client.disconnect()

    @staticmethod
    def _in_period(value: datetime, start: datetime | None, end: datetime | None) -> bool:
        value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if start is not None and value < (start if start.tzinfo else start.replace(tzinfo=timezone.utc)):
            return False
        return end is None or value <= (end if end.tzinfo else end.replace(tzinfo=timezone.utc))

    @staticmethod
    def _message_dto(message: Any) -> TelegramMessageDTO:
        replies = getattr(message, "replies", None)
        return TelegramMessageDTO(
            id=int(message.id),
            text=str(getattr(message, "message", "") or ""),
            published_at=message.date if message.date.tzinfo else message.date.replace(tzinfo=timezone.utc),
            views=int(getattr(message, "views", 0) or 0),
            forwards=int(getattr(message, "forwards", 0) or 0),
            comments_count=int(getattr(replies, "replies", 0) or 0),
            content_type=TelegramApiClient._content_type(message),
        )

    @staticmethod
    def _comment_dto(message: Any) -> TelegramCommentDTO:
        reply = getattr(message, "reply_to", None)
        sender = getattr(message, "sender", None)
        name = " ".join(
            item for item in [getattr(sender, "first_name", None), getattr(sender, "last_name", None)] if item
        ) or getattr(sender, "title", None)
        return TelegramCommentDTO(
            id=int(message.id),
            text=str(getattr(message, "message", "") or "").strip(),
            author_id=str(getattr(message, "sender_id", "") or "") or None,
            author_name=name,
            published_at=getattr(message, "date", None),
            parent_id=getattr(reply, "reply_to_msg_id", None),
        )

    @staticmethod
    def _content_type(message: Any) -> str:
        if getattr(message, "poll", None):
            return "poll"
        if getattr(message, "video", None):
            return "video"
        if getattr(message, "photo", None):
            return "photo"
        return "other" if getattr(message, "media", None) else "text"
