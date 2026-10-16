"""Доменные ошибки VK-модуля."""

from typing import Optional


class VkApiError(RuntimeError):
    """Ошибка VK API. code — VK error_code, либо None для сетевых проблем."""

    def __init__(self, message: str, code: Optional[int] = None) -> None:
        """Инициализирует ошибку VK API."""
        super().__init__(message)
        self.code = code


class VKAPIError(RuntimeError):
    """Ошибка VK API или сети при публикации/парсинге стены."""


class InvalidVKUrlError(ValueError):
    """Невалидная ссылка/идентификатор VK-сообщества."""


class IngestionError(RuntimeError):
    """Доменная ошибка импорта VK-ссылки."""

class InvalidVkLinkError(ValueError):
    """Невалидная VK-ссылка."""
