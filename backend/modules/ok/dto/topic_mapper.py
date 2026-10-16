"""Мапперы сырых OK-объектов в DTO/поля БД."""

from datetime import datetime, timezone
from typing import Any

from backend.db import ContentTypeEnum, PostOriginEnum
from backend.modules.ok.dto.dto import OkTopicStatsDTO


class OkTopicMapper:
    """Содержит только преобразование OK-тем без IO и БД."""

    def topic_id(self, topic: dict[str, Any]) -> str:
        """Возвращает id медиатопика."""

        return str(topic.get("id") or "")

    def external_post_id(self, group_id: str, topic: dict[str, Any]) -> str:
        """Возвращает внешний id вида <group_id>_<topic_id>."""

        return f"{group_id}_{self.topic_id(topic)}"

    def post_url(self, group_id: str, topic: dict[str, Any]) -> str:
        """Возвращает URL темы OK."""

        return f"https://ok.ru/group/{group_id}/topic/{self.topic_id(topic)}"

    def published_at(self, topic: dict[str, Any]) -> datetime:
        """Возвращает дату публикации темы."""

        created_ms = topic.get("created_ms")
        if created_ms:
            return datetime.fromtimestamp(int(created_ms) / 1000, tz=timezone.utc)
        return datetime.now(timezone.utc)

    def extract_text(self, topic: dict[str, Any]) -> str:
        """Склеивает текст из текстовых блоков медиатопика.

        OK отдаёт текст либо готовой строкой, либо набором ``text_tokens``.
        """

        chunks: list[str] = []
        for block in self._media_blocks(topic):
            if str(block.get("type") or "").lower() != "text":
                continue
            text = block.get("text")
            if not text:
                tokens = block.get("text_tokens") or []
                text = "".join(str(token.get("text") or "") for token in tokens)
            if text:
                chunks.append(str(text).strip())

        if chunks:
            return "\n".join(chunk for chunk in chunks if chunk).strip()
        return str(topic.get("title") or "").strip()

    def detect_content_type(self, topic: dict[str, Any]) -> ContentTypeEnum:
        """Определяет тип контента темы по её медиа-блокам."""

        types = {str(block.get("type") or "").lower() for block in self._media_blocks(topic)}
        types.discard("text")
        if not types:
            return ContentTypeEnum.text
        if "video" in types and "photo" in types:
            return ContentTypeEnum.mixed
        if "video" in types:
            return ContentTypeEnum.video
        if "photo" in types:
            return ContentTypeEnum.photo
        if "poll" in types:
            return ContentTypeEnum.poll
        return ContentTypeEnum.other

    def metadata_tags(self, topic: dict[str, Any]) -> list[str]:
        """Возвращает теги для sync_post_tags."""

        return ["ok", PostOriginEnum.parsed.value, self.detect_content_type(topic).value]

    def stats(self, stat_topic: dict[str, Any]) -> OkTopicStatsDTO:
        """Нормализует агрегаты темы из group.getStatTopics."""

        return OkTopicStatsDTO(
            topic_id=str(stat_topic.get("id") or ""),
            likes=int(stat_topic.get("likes") or 0),
            comments=int(stat_topic.get("comments") or 0),
            reshares=int(stat_topic.get("reshares") or 0),
            views=int(stat_topic.get("views") or stat_topic.get("reach") or 0),
        )

    def extract_media_entries(self, topic: dict[str, Any]) -> list[dict[str, Any]]:
        """Извлекает медиа-вложения темы в унифицированный формат."""

        items: list[dict[str, Any]] = []
        for index, block in enumerate(self._media_blocks(topic)):
            block_type = str(block.get("type") or "").lower()
            if block_type == "photo":
                items.extend(self._photo_entries(block, index))
            elif block_type == "video":
                url = block.get("url") or block.get("playerUrl")
                if url:
                    items.append(
                        {
                            "url": url,
                            "type": ContentTypeEnum.video,
                            "external_id": str(block.get("id") or ""),
                            "sort_order": index,
                        }
                    )
            elif block_type == "link":
                url = block.get("url") or (block.get("linkInfo") or {}).get("url")
                if url:
                    items.append(
                        {
                            "url": url,
                            "type": ContentTypeEnum.other,
                            "external_id": "",
                            "sort_order": index,
                        }
                    )
        return items

    def comment_text(self, comment: dict[str, Any]) -> str:
        """Возвращает текст комментария (строкой или из text_tokens)."""

        text = comment.get("text")
        if text:
            return str(text).strip()
        tokens = comment.get("text_tokens") or []
        return "".join(str(token.get("text") or "") for token in tokens).strip()

    def comment_author_id(self, comment: dict[str, Any]) -> str | None:
        """Возвращает внешний id автора комментария.

        OK отдаёт ссылку вида ``user:123456`` в ``author_ref`` либо голый
        ``author_id``.
        """

        author_id = comment.get("author_id")
        if author_id:
            return str(author_id)
        author_ref = comment.get("author_ref") or comment.get("actual_user_author_ref")
        if not author_ref:
            return None
        return str(author_ref).split(":", 1)[-1] or None

    def comment_date(self, comment: dict[str, Any]) -> datetime | None:
        """Возвращает дату комментария."""

        created_ms = comment.get("created_ms") or comment.get("date_ms")
        if not created_ms:
            return None
        return datetime.fromtimestamp(int(created_ms) / 1000, tz=timezone.utc)

    def comment_parent_id(self, comment: dict[str, Any]) -> str | None:
        """Возвращает внешний id родительского комментария, если он есть."""

        parent = comment.get("reply_to_comment_id") or comment.get("reply_to_id")
        return str(parent) if parent else None

    def _media_blocks(self, topic: dict[str, Any]) -> list[dict[str, Any]]:
        """Возвращает медиа-блоки темы."""

        media = topic.get("media") or []
        return [block for block in media if isinstance(block, dict)]

    def _photo_entries(self, block: dict[str, Any], index: int) -> list[dict[str, Any]]:
        """Разворачивает фото-блок: OK кладёт фото и одиночно, и списком."""

        photos = block.get("list") or []
        if not photos and isinstance(block.get("photo"), dict):
            photos = [block["photo"]]

        entries: list[dict[str, Any]] = []
        for photo in photos:
            if not isinstance(photo, dict):
                continue
            url = self._pick_photo_url(photo)
            if url:
                entries.append(
                    {
                        "url": url,
                        "type": ContentTypeEnum.photo,
                        "external_id": str(photo.get("id") or ""),
                        "sort_order": index,
                    }
                )
        return entries

    def _pick_photo_url(self, photo: dict[str, Any]) -> str | None:
        """Выбирает самую крупную доступную превьюшку фото."""

        for key in ("pic1024x768", "pic640x480", "pic320min", "picUrl", "url"):
            url = photo.get(key)
            if url:
                return str(url)

        sizes = photo.get("sizes") or []
        if not sizes:
            return None
        best = max(sizes, key=lambda item: int(item.get("width") or 0))
        return best.get("url")
