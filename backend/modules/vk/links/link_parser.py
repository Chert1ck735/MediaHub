"""Сервис-парсер VK-ссылок."""
from backend.modules.vk.dto.dto import VkLinkRef
from backend.modules.vk.links.links import parse_vk_link


class VkLinkParser:
    """Оборачивает чистую функцию parse_vk_link в интерфейсный сервис."""

    def parse(self, raw: str) -> VkLinkRef:
        """Распознаёт VK-ссылку как community/profile/post."""

        return parse_vk_link(raw)
