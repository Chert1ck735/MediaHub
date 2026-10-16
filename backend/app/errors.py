"""Хелперы для безопасной обработки ошибок в endpoint'ах.

Главная мысль: оригинальный текст generic Exception НЕ должен попадать в
HTTPException.detail, потому что там могут просвечивать имена таблиц/полей,
ключи API, фрагменты SQL и т.п. На prod это утечка.

Доменные ошибки (наследники собственных XxxError) — можно отдавать как есть,
их текст контролируется кодом.

Использование:
    try:
        ...
    except SomeDomainError as e:
        raise HTTPException(400, detail=str(e))   # это ок
    except Exception as e:
        raise internal_error(e, logger, "Ошибка при формировании отчёта")
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, status


def internal_error(
    exc: BaseException,
    logger_: logging.Logger,
    user_message: str = "Internal server error",
    *,
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
) -> HTTPException:
    """Логирует traceback и возвращает HTTPException с безопасным текстом (без утечки деталей в response)."""
    logger_.exception("Unhandled exception: %s", exc)
    return HTTPException(status_code=http_status, detail=user_message)
