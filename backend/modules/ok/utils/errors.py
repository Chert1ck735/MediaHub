"""Доменные ошибки OK-модуля."""

from typing import Optional


class OkApiError(RuntimeError):
    """Ошибка OK API. code — error_code Одноклассников, либо None для сети."""

    def __init__(self, message: str, code: Optional[int] = None) -> None:
        """Инициализирует ошибку OK API."""
        super().__init__(message)
        self.code = code


class OkIngestionError(RuntimeError):
    """Доменная ошибка импорта OK-ссылки."""


class InvalidOkLinkError(ValueError):
    """Невалидная ссылка Одноклассников."""
