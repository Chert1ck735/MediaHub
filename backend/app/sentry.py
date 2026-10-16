"""Инициализация Sentry и контекст ошибок.

Раньше в Sentry улетали ТОЛЬКО необработанные исключения HTTP-ручек. А в коде
61 место вида ``except Exception: logger.exception(...)`` — ошибка гасится, в
логе остаётся, до Sentry не доходит. Плюс фоновые задачи (классификация,
ингест, воркеры) живут в отдельных asyncio-тасках, куда обработчик FastAPI не
дотягивается вовсе. То есть больше всего падало ровно там, где мы этого не
видели.

Теперь:

* ``LoggingIntegration`` — каждый ``logger.error`` / ``logger.exception``
  становится событием Sentry. Это разом закрывает те самые 61 место, не трогая
  их код;
* ``before_send`` отсекает шум: 4xx — это поведение приложения, а не поломка
  (клиент прислал мусор), и заваливать ими Sentry значит утопить в них реальные
  5xx;
* персональные данные и секреты вычищаются из событий: письма, пароли, токены,
  строка подключения к БД. ``send_default_pii=False`` этого НЕ гарантирует — он
  лишь запрещает Sentry собирать их автоматически, а то, что мы сами положили в
  сообщение об ошибке, уедет как есть;
* ``enable_logs`` (Sentry Structured Logs) — INFO+ логи уходят в отдельную
  ленту логов Sentry, а не только ошибки. Их можно листать и искать (проходы
  автопарсера/воркеров и т.п.). Логи идут МИМО ``before_send``, поэтому та же
  очистка PII/секретов повторена в ``before_send_log``. Выключается флагом
  ``SENTRY_ENABLE_LOGS=false``.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from backend.app.config import settings

logger = logging.getLogger(__name__)

# Ключи, значение которых не должно покидать сервер ни при каких обстоятельствах.
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "raw_password",
        "new_password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "secret",
        "smtp_password",
        "db_pass",
        "code",  # код подтверждения из письма
    }
)

# Строка подключения к БД целиком: она попадает в текст ошибок asyncpg/SQLAlchemy
# вместе с логином и паролем.
_DSN_RE = re.compile(r"(postgresql[^\s'\"]*://)[^@\s'\"]+@", re.IGNORECASE)

# Email в тексте сообщений — персональные данные.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Секреты в query-строке. Сетевые ошибки приходят с полным URL запроса, а в нём
# лежат access_token VK и apikey геокодера — и уезжали в трекер как есть.
_QUERY_SECRET_RE = re.compile(
    r"(access_token|apikey|api_key|token|secret|password)=[^&\s'\"\)]+",
    re.IGNORECASE,
)


def _scrub_text(value: str) -> str:
    value = _DSN_RE.sub(r"\1***:***@", value)
    value = _QUERY_SECRET_RE.sub(r"\1=[filtered]", value)
    return _EMAIL_RE.sub("<email>", value)


def _scrub(obj: Any) -> Any:
    """Рекурсивно вычищает секреты и персданные из события."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
                out[key] = "[filtered]"
            else:
                out[key] = _scrub(value)
        return out
    if isinstance(obj, list):
        return [_scrub(item) for item in obj]
    if isinstance(obj, str):
        return _scrub_text(obj)
    return obj


def _before_send_log(record: dict, hint: dict) -> dict | None:
    """Чистит структурный лог перед отправкой в Sentry Logs.

    Логи идут МИМО ``before_send`` (тот только для Issues), поэтому ту же
    очистку писем/DSN/секретов повторяем здесь — иначе ``logger.info`` вида
    "Login attempt | email=..." утёк бы в ленту логов как есть.
    """
    body = record.get("body")
    if isinstance(body, str):
        record["body"] = _scrub_text(body)
    attributes = record.get("attributes")
    if isinstance(attributes, dict):
        record["attributes"] = _scrub(attributes)
    return record


def _before_send(event: dict, hint: dict) -> dict | None:
    """Фильтрует шум и чистит событие перед отправкой."""
    exc_info = hint.get("exc_info")
    if exc_info:
        exc = exc_info[1]

        # HTTPException 4xx — это НЕ поломка: клиент прислал мусор, не туда
        # полез, ввёл неверный код. Такие события в Sentry только шумят и
        # прячут настоящие 5xx. Пропускаем только серверные ошибки.
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and 400 <= status_code < 500:
            return None

        # Отмена задачи пользователем и штатное завершение — не ошибки.
        if exc.__class__.__name__ in {"JobCancelled", "CancelledError"}:
            return None

    return _scrub(event)


def init_sentry() -> None:
    """Поднимает Sentry. Без DSN — тихо ничего не делает (dev)."""
    dsn = settings.SENTRY_DSN.strip()
    if not dsn:
        logger.info("SENTRY_DSN не задан — трекинг ошибок выключен")
        return

    # Structured Logs: INFO+ логи уходят в Sentry как лента (просмотр проходов
    # воркеров/автопарсера, а не только ошибок). Идут мимо before_send, поэтому
    # чистятся отдельным before_send_log. Флагом можно выключить.
    experiments: dict[str, Any] = {}
    if settings.SENTRY_ENABLE_LOGS:
        experiments["enable_logs"] = True
        experiments["before_send_log"] = _before_send_log

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.APP_ENV,
        release=settings.SENTRY_RELEASE or None,
        # Трейсинг производительности по умолчанию выключен: он дорогой, а нам
        # нужны ошибки. Включается через SENTRY_TRACES_SAMPLE_RATE.
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,
        before_send=_before_send,
        _experiments=experiments,
        integrations=[
            # Главное: logger.error / logger.exception -> событие Sentry.
            # Именно это закрывает 61 место, где ошибка гаснет в except.
            # sentry_logs_level=INFO — те же записи уходят в Sentry Logs (если
            # включено enable_logs выше).
            LoggingIntegration(
                level=logging.INFO,          # INFO и выше идут в хлебные крошки
                event_level=logging.ERROR,   # ERROR и выше становятся событиями
                sentry_logs_level=logging.INFO,  # INFO и выше -> Sentry Logs
            ),
            # Ошибки в asyncio-тасках (фоновые воркеры, jobs) — иначе они
            # тонут: HTTP-обработчик до них не дотягивается.
            AsyncioIntegration(),
            StarletteIntegration(),
            FastApiIntegration(),
            SqlalchemyIntegration(),
        ],
    )
    logger.info("Sentry подключён | env=%s", settings.APP_ENV)


def set_user_context(*, user_id: str | None, organization_id: str | None) -> None:
    """Привязывает ошибку к пользователю и организации.

    Без этого событие «упало в аналитике» бесполезно: непонятно, у кого и в
    какой организации. Почту и имя НЕ пишем — id достаточно, чтобы найти
    человека в базе, и это не персданные в трекере.
    """
    sentry_sdk.set_user({"id": user_id} if user_id else None)
    if organization_id:
        sentry_sdk.set_tag("organization_id", organization_id)


def capture(exc: BaseException, **context: Any) -> None:
    """Отправляет исключение с дополнительным контекстом.

    Для мест, где ошибку глотают осознанно (fallback сработал, задача
    продолжается), но знать о ней всё равно надо.
    """
    with sentry_sdk.new_scope() as scope:
        for key, value in _scrub(context).items():
            scope.set_extra(key, value)
        sentry_sdk.capture_exception(exc)
