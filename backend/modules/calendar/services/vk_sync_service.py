"""Сервис синхронизации календарных публикаций с VK."""

from datetime import datetime, timezone

from backend.db import Publication, Post, PublicSocialLink
from backend.modules.calendar.utils.errors import CalendarExternalServiceError, CalendarValidationError
from backend.modules.calendar.utils.interfaces import CalendarVkPostingProtocol
from backend.modules.vk.dto.dto import EditVkPostDTO, CreateVkPostDTO
from backend.modules.vk.services.posting_service import VkPostingService
from backend.modules.vk.utils.errors import VkApiError, VKAPIError


def _vk_owner_id_for_link(link: PublicSocialLink) -> int | None:
    """Возвращает owner_id VK по PublicSocialLink."""

    external_public_id = (link.external_public_id or "").strip()
    if not external_public_id.isdigit():
        return None
    return -int(external_public_id)


def _vk_message_for_post(post: Post) -> str:
    """Собирает текст VK-публикации из Post."""

    body = (post.text_generated or post.text_draft or "").strip()
    title = (post.title or "").strip()
    if title and body:
        return f"{title}\n\n{body}"
    return title or body


class CalendarVkSyncService:
    """Создает, обновляет и удаляет отложенные публикации VK."""

    def __init__(self, posting_service: CalendarVkPostingProtocol | None = None) -> None:
        self.posting_service = posting_service or VkPostingService()

    def sync_scheduled_publication(self, publication: Publication, post: Post) -> None:
        """Создает или обновляет отложенную публикацию VK."""

        link = publication.__dict__.get("public_social_link")
        network = link.__dict__.get("social_network") if link else None

        if not link or not network or network.code != "vk":
            return
        if publication.status.value != "scheduled" or not publication.scheduled_at:
            return

        owner_id = _vk_owner_id_for_link(link)
        if owner_id is None:
            raise CalendarValidationError(
                "Для выбранного VK-паблика не найден numeric external_public_id"
            )

        message = _vk_message_for_post(post).strip()
        if not message:
            raise CalendarValidationError("Нельзя запланировать пустой пост в VK")

        if publication.external_post_id and publication.external_post_id.isdigit():
            vk_post_id = self._edit_existing_publication(publication, message, owner_id)
        else:
            vk_post_id = self._create_new_publication(publication, message, owner_id)
            publication.external_post_id = str(vk_post_id)

        publication.url = self.posting_service.post_url(vk_post_id, owner_id=owner_id)
        publication.error_message = None
        publication.last_synced_at = datetime.now(timezone.utc)

    def delete_scheduled_publication(self, publication: Publication) -> None:
        """Удаляет отложенную VK-публикацию, если она есть."""

        link = publication.__dict__.get("public_social_link")
        network = link.__dict__.get("social_network") if link else None

        if not link or not network or network.code != "vk":
            return
        if not publication.external_post_id or not publication.external_post_id.isdigit():
            return

        owner_id = _vk_owner_id_for_link(link)
        if owner_id is None:
            return

        self.posting_service.delete_post(int(publication.external_post_id), owner_id=owner_id)

    def _create_new_publication(self, publication: Publication, message: str, owner_id: int) -> int:
        """Создает новый отложенный VK-пост."""
        try:
            return self.posting_service.create_post(
                CreateVkPostDTO(
                    message=message,
                    from_group=True,
                    owner_id=owner_id,
                    publish_date=publication.scheduled_at,
                )
            )
        except (VKAPIError, VkApiError) as error:
            self._raise_vk_schedule_error(error)
        raise AssertionError("unreachable")

    def _edit_existing_publication(
        self,
        publication: Publication,
        message: str,
        owner_id: int,
    ) -> int:
        """Обновляет существующий отложенный VK-пост."""
        try:
            ok = self.posting_service.edit_post(
                EditVkPostDTO(
                    post_id=int(publication.external_post_id),
                    message=message,
                    owner_id=owner_id,
                    publish_date=publication.scheduled_at,
                )
            )
        except (VKAPIError, VkApiError) as error:
            self._raise_vk_schedule_error(error)
            raise AssertionError("unreachable")

        if not ok:
            raise CalendarExternalServiceError("VK не подтвердил обновление отложенного поста")

        return int(publication.external_post_id)

    def _raise_vk_schedule_error(self, error: Exception) -> None:
        """Преобразует ошибку VK в доменную ошибку календаря."""

        message = str(error)
        if "already scheduled for this time" in message.lower():
            raise CalendarValidationError(
                "На это время в VK уже запланирован пост. Выберите другое время."
            ) from error
        raise CalendarExternalServiceError(
            f"VK не разрешил запланировать пост: {message}"
        ) from error
