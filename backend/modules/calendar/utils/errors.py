"""Доменные ошибки календарного модуля."""


class CalendarError(Exception):
    """Базовая ошибка календарного модуля."""


class CalendarNotFoundError(CalendarError):
    """Объект календаря не найден или недоступен пользователю."""


class CalendarValidationError(CalendarError):
    """Переданы некорректные данные календарного события."""


class CalendarExternalServiceError(CalendarError):
    """Внешний сервис не выполнил календарную операцию."""
