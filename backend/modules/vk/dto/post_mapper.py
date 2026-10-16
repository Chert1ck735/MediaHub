"""Мапперы сырых VK-объектов в DTO/поля БД."""

from datetime import datetime
from typing import Any

from backend.db import ContentTypeEnum, PostOriginEnum
from backend.modules.vk.dto.dto import ParsedVkPostDTO


class VkPostMapper:
    """Содержит только преобразование VK-постов без IO и БД."""

    def to_parsed_dto(self, post: dict[str, Any]) -> ParsedVkPostDTO:
        """Преобразует сырой VK-пост в DTO для API-ответа."""

        return ParsedVkPostDTO(
            id=post.get("id"),
            date=datetime.fromtimestamp(post.get("date", 0)),
            text=(post.get("text", "") or "").replace("\n", " ").replace(";", ","),
            reposts=(post.get("reposts") or {}).get("count", 0),
            likes=(post.get("likes") or {}).get("count", 0),
            comments=(post.get("comments") or {}).get("count", 0),
            views=(post.get("views") or {}).get("count", 0),
        )

    def detect_content_type(self, vk_post: dict[str, Any]) -> ContentTypeEnum:
        """Определяет тип контента поста по attachments."""

        attachments = vk_post.get("attachments", []) or []
        if not attachments:
            return ContentTypeEnum.text
        types = {a.get("type") for a in attachments}
        if "video" in types and "photo" in types:
            return ContentTypeEnum.mixed
        if "video" in types:
            return ContentTypeEnum.video
        if "photo" in types:
            return ContentTypeEnum.photo
        if "doc" in types:
            return ContentTypeEnum.document
        if "poll" in types:
            return ContentTypeEnum.poll
        return ContentTypeEnum.other

    def external_post_id(self, vk_post: dict[str, Any]) -> str:
        """Возвращает внешний id вида owner_post."""

        return f"{vk_post.get('owner_id')}_{vk_post.get('id')}"

    def post_url(self, vk_post: dict[str, Any]) -> str:
        """Возвращает URL поста VK."""

        return f"https://vk.com/wall{self.external_post_id(vk_post)}"

    def metadata_tags(self, vk_post: dict[str, Any]) -> list[str]:
        """Возвращает теги для sync_post_tags."""

        return ["vk", PostOriginEnum.parsed.value, self.detect_content_type(vk_post).value]

    def extract_media_entries(self, vk_post: dict[str, Any]) -> list[dict[str, Any]]:
        """Извлекает медиа-вложения поста в унифицированный формат."""

        items: list[dict[str, Any]] = []
        for index, attachment in enumerate(vk_post.get("attachments", []) or []):
            attachment_type = str(attachment.get("type") or "")
            payload = attachment.get(attachment_type) or {}
            if attachment_type == "photo":
                url = self._pick_photo_url(payload)
                if url:
                    items.append({"url": url, "type": ContentTypeEnum.photo, "external_id": str(payload.get("id") or ""), "sort_order": index})
            elif attachment_type == "video":
                owner_id = payload.get("owner_id")
                video_id = payload.get("id")
                url = payload.get("player") or (
                    f"https://vk.com/video{owner_id}_{video_id}"
                    if owner_id is not None and video_id is not None
                    else None
                )
                if url:
                    items.append({"url": url, "type": ContentTypeEnum.video, "external_id": str(video_id or ""), "sort_order": index})
            elif attachment_type == "doc":
                url = payload.get("url")
                if url:
                    items.append({"url": url, "type": ContentTypeEnum.document, "external_id": str(payload.get("id") or ""), "sort_order": index})
        return items

    def _pick_photo_url(self, photo: dict[str, Any]) -> str | None:
        """Выбирает самую крупную фотографию из sizes."""

        sizes = photo.get("sizes") or []
        if not sizes:
            return None
        best = max(sizes, key=lambda item: (int(item.get("width") or 0), int(item.get("height") or 0)))
        return best.get("url")
