"""Сервис публикации, редактирования, удаления и загрузки фото VK."""

import logging
import time
from datetime import timezone, datetime
from typing import Optional

import requests

from backend.app.config import settings
from backend.modules.vk.dto.dto import EditVkPostDTO, UploadPhotoDTO, CreateVkPostDTO
from backend.modules.vk.utils.constants import POSTING_MAX_RETRIES, POSTING_RETRY_DELAY_SEC
from backend.modules.vk.utils.errors import VKAPIError

logger = logging.getLogger(__name__)


class VkPostingService:
    """Инкапсулирует команды, изменяющие стену VK."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def create_post(self, dto: CreateVkPostDTO) -> int:
        """Публикует пост на стену сообщества и возвращает ID поста."""

        params = {
            "owner_id": settings.OWNER_ID if dto.owner_id is None else int(dto.owner_id),
            "from_group": int(dto.from_group),
            "message": dto.message,
            "v": settings.VK_API_VERSION,
            "access_token": settings.ACCESS_TOKEN,
        }
        if dto.attachments:
            params["attachments"] = dto.attachments
        if dto.publish_date is not None:
            params["publish_date"] = self._to_timestamp(dto.publish_date)
        data = self._post_with_retries(settings.VK_API_URL_POST, params)
        if "error" in data:
            raise VKAPIError(data["error"].get("error_msg", "VK API error"))
        return int(data["response"]["post_id"])

    def edit_post(self, dto: EditVkPostDTO) -> bool:
        """Редактирует пост VK."""

        params = {
            "owner_id": settings.OWNER_ID if dto.owner_id is None else int(dto.owner_id),
            "post_id": int(dto.post_id),
            "message": dto.message,
            "v": settings.VK_API_VERSION,
            "access_token": settings.ACCESS_TOKEN,
        }
        if dto.attachments:
            params["attachments"] = dto.attachments
        if dto.publish_date is not None:
            params["publish_date"] = self._to_timestamp(dto.publish_date)
        data = self._post_with_retries("https://api.vk.com/method/wall.edit", params)
        if "error" in data:
            raise VKAPIError(data["error"].get("error_msg", "VK API error"))
        return bool(data.get("response", 0))

    def delete_post(self, post_id: int, owner_id: Optional[int] = None) -> bool:
        """Удаляет пост со стены сообщества."""

        params = {
            "owner_id": settings.OWNER_ID if owner_id is None else int(owner_id),
            "post_id": post_id,
            "v": settings.VK_API_VERSION,
            "access_token": settings.ACCESS_TOKEN,
        }
        data = self._post_with_retries("https://api.vk.com/method/wall.delete", params)
        if "error" in data:
            raise VKAPIError(data["error"].get("error_msg", "VK API error"))
        return bool(data.get("response", 0))

    def upload_wall_photo(self, dto: UploadPhotoDTO) -> str:
        """Загружает фото на стену сообщества VK и возвращает attachment."""

        logger.info("upload_wall_photo: filename=%s content_type=%s size=%d", dto.filename, dto.content_type, len(dto.file_bytes))
        server_data = self._get_with_retries(
            "https://api.vk.com/method/photos.getWallUploadServer",
            {"group_id": settings.GROUP_ID, "v": settings.VK_API_VERSION, "access_token": settings.ACCESS_TOKEN},
        )
        if "error" in server_data:
            raise VKAPIError(server_data["error"].get("error_msg", "VK API error (getWallUploadServer)"))
        upload_url = server_data["response"]["upload_url"]
        try:
            resp = self._session.post(upload_url, files={"photo": (dto.filename, dto.file_bytes, dto.content_type)}, timeout=30)
            upload_result = resp.json()
        except (requests.exceptions.RequestException, ValueError) as exc:
            raise VKAPIError(f"Ошибка загрузки фото на сервер VK: {exc}") from exc
        if not upload_result.get("photo") or upload_result.get("photo") == "[]":
            raise VKAPIError("VK не принял фото (пустой ответ после загрузки)")
        save_data = self._post_with_retries(
            "https://api.vk.com/method/photos.saveWallPhoto",
            {
                "group_id": settings.GROUP_ID,
                "photo": upload_result["photo"],
                "server": upload_result["server"],
                "hash": upload_result["hash"],
                "v": settings.VK_API_VERSION,
                "access_token": settings.ACCESS_TOKEN,
            },
        )
        if "error" in save_data:
            raise VKAPIError(save_data["error"].get("error_msg", "VK API error (saveWallPhoto)"))
        photo = save_data["response"][0]
        return f"photo{photo['owner_id']}_{photo['id']}"

    def post_url(self, post_id: int, owner_id: Optional[int] = None) -> str:
        """Строит URL поста."""
        owner = settings.OWNER_ID if owner_id is None else int(owner_id)
        return f"https://vk.com/wall{owner}_{post_id}"

    def _to_timestamp(self, value: datetime | int) -> int:
        """Преобразует datetime/int в unix timestamp."""

        if isinstance(value, datetime):
            dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return int(dt.astimezone(timezone.utc).timestamp())
        return int(value)

    def _post_with_retries(self, url: str, params: dict) -> dict:
        """POST с retry."""

        last_err: Optional[Exception] = None
        for _ in range(POSTING_MAX_RETRIES):
            try:
                resp = self._session.post(url, data=params, timeout=15)
                return resp.json()
            except (requests.exceptions.RequestException, ValueError) as exc:
                last_err = exc
                time.sleep(POSTING_RETRY_DELAY_SEC)
        raise VKAPIError(f"VK POST {url} не ответил после {POSTING_MAX_RETRIES} попыток: {last_err}")

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


_default_service = VkPostingService()


def create_post(message: str, attachments: Optional[str] = None, from_group: bool = True, owner_id: Optional[int] = None, publish_date: Optional[datetime | int] = None) -> int:
    """Backward-compatible wrapper."""

    return _default_service.create_post(CreateVkPostDTO(message, attachments, from_group, owner_id, publish_date))


def edit_post(post_id: int, message: str, attachments: Optional[str] = None, owner_id: Optional[int] = None, publish_date: Optional[datetime | int] = None) -> bool:
    """Backward-compatible wrapper."""

    return _default_service.edit_post(EditVkPostDTO(post_id, message, attachments, owner_id, publish_date))


def delete_post(post_id: int, owner_id: Optional[int] = None) -> bool:
    """Backward-compatible wrapper."""

    return _default_service.delete_post(post_id, owner_id)


def upload_wall_photo(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Backward-compatible wrapper."""

    return _default_service.upload_wall_photo(UploadPhotoDTO(file_bytes, filename, content_type))


def post_url(post_id: int, owner_id: Optional[int] = None) -> str:
    """Backward-compatible wrapper."""

    return _default_service.post_url(post_id, owner_id)
