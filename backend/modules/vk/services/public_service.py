"""Сервис выбора дефолтного VK-паблика."""

from backend.app.config import settings
from backend.db import User
from backend.modules.vk.repositories.public_repository import VkPublicRepository


class VkPublicService:
    """Содержит бизнес-логику выбора дефолтного паблика для публикации."""

    def __init__(self, repository: VkPublicRepository) -> None:
        self.repository = repository

    async def get_default_public(self, user: User):
        """Возвращает PublicSocialLink или None по старому алгоритму router."""

        network = await self.repository.get_vk_network()
        if not network:
            return None

        if settings.GROUP_ID > 0:
            link = await self.repository.find_by_group_id(user, settings.GROUP_ID)
            if link:
                return link

        fallback_rows = await self.repository.get_fallback_links(user)
        if settings.GROUP_ID > 0:
            return await self.repository.create_missing_default_vk_public(user=user, network=network)
        if len(fallback_rows) == 1:
            return fallback_rows[0]
        return None
