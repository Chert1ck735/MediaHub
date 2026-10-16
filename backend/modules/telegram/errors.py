class TelegramConfigurationError(RuntimeError):
    """Не заданы реквизиты MTProto или WPS-прокси."""


class InvalidTelegramLinkError(ValueError):
    """Ссылка не является поддерживаемой публичной ссылкой Telegram."""


class TelegramIngestionError(RuntimeError):
    """Публичная ошибка импорта Telegram-канала."""

