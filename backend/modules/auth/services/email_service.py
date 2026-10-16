"""Отправка писем через SMTP.

``smtplib`` — синхронная библиотека, поэтому отправка уходит в threadpool через
``asyncio.to_thread``. Позвать её напрямую из ``async def`` нельзя: пока SMTP
жуёт TLS-рукопожатие и ждёт ответа сервера (это секунды, а на сбоящем релее —
до таймаута), встанет ВЕСЬ event loop, то есть все параллельные запросы, а не
только регистрация. Отдельной async-библиотеки ради этого не тянем: письма —
редкая операция, поток дешевле новой зависимости.

Если SMTP не настроен:
* на проде — ошибка. Молча «отправить» письмо, которого нет, значит запереть
  пользователя на экране ввода кода без единого способа его узнать;
* в dev — код пишется в лог сервера с явным предупреждением. В ОТВЕТ КЛИЕНТУ
  код не попадает никогда, ни при каких настройках.
"""
from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage

from backend.app.config import settings
from backend.app.logger_config import get_logger

# Через get_logger, а не logging.getLogger: без SMTP код уходит в лог, и в dev
# его надо уметь найти в файле, а не выуживать из консоли.
logger = get_logger(__name__)


class EmailNotConfiguredError(RuntimeError):
    """SMTP не настроен, а отправить письмо необходимо."""


class EmailDeliveryError(RuntimeError):
    """SMTP настроен, но письмо не ушло."""


def is_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)


def _sender() -> str:
    return settings.SMTP_FROM or settings.SMTP_USER


def _send_blocking(message: EmailMessage) -> None:
    """Синхронная отправка. Вызывается только из threadpool."""
    context = ssl.create_default_context()

    if settings.SMTP_USE_SSL:
        # 465: TLS с первого байта.
        with smtplib.SMTP_SSL(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT,
            context=context,
        ) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(message)
        return

    # 587: открытое соединение, затем STARTTLS.
    with smtplib.SMTP(
        settings.SMTP_HOST,
        settings.SMTP_PORT,
        timeout=settings.SMTP_TIMEOUT,
    ) as server:
        if settings.SMTP_USE_TLS:
            server.starttls(context=context)
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(message)


async def send_email(*, to: str, subject: str, text: str, html: str | None = None) -> None:
    """Отправляет письмо. Бросает ``EmailDeliveryError``, если не удалось."""
    if not is_configured():
        raise EmailNotConfiguredError("SMTP не настроен")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.SMTP_FROM_NAME} <{_sender()}>"
    message["To"] = to
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")

    try:
        await asyncio.to_thread(_send_blocking, message)
    except Exception as exc:  # noqa: BLE001 — наружу отдаём один понятный тип
        # В лог — причина; клиенту наружу её не показываем (там могут быть
        # адреса релея и логины).
        logger.exception("Не удалось отправить письмо на %s", to)
        raise EmailDeliveryError(str(exc)) from exc


async def send_verification_code(*, to: str, code: str) -> None:
    """Письмо с кодом подтверждения регистрации."""
    ttl = settings.EMAIL_CODE_TTL_MINUTES
    subject = f"{code} — код подтверждения"

    text = (
        f"Код подтверждения регистрации: {code}\n\n"
        f"Код действует {ttl} минут.\n"
        "Если вы не запрашивали код — просто проигнорируйте это письмо."
    )
    html = f"""
      <div style="font-family:system-ui,sans-serif;max-width:420px">
        <p>Код подтверждения регистрации:</p>
        <p style="font-size:32px;font-weight:700;letter-spacing:6px;margin:16px 0">{code}</p>
        <p style="color:#64748b">Код действует {ttl} минут.</p>
        <p style="color:#64748b">
          Если вы не запрашивали код — просто проигнорируйте это письмо.
        </p>
      </div>
    """

    if not is_configured():
        # Dev-режим: без SMTP код виден только в логе сервера, но НЕ в ответе API.
        if settings.APP_ENV.lower() == "prod":
            raise EmailNotConfiguredError(
                "SMTP не настроен: письмо с кодом отправить невозможно"
            )
        logger.warning(
            "SMTP не настроен — письмо не отправлено. Код для %s: %s "
            "(так работает только dev; задайте SMTP_* в .env)",
            to,
            code,
        )
        return

    await send_email(to=to, subject=subject, text=text, html=html)


async def send_password_reset_code(*, to: str, code: str) -> None:
    """Письмо с кодом для восстановления пароля."""
    ttl = settings.EMAIL_CODE_TTL_MINUTES
    subject = f"{code} — код для смены пароля"

    text = (
        f"Код для смены пароля: {code}\n\n"
        f"Код действует {ttl} минут.\n"
        "Если вы не запрашивали смену пароля — просто проигнорируйте это письмо, "
        "пароль останется прежним."
    )
    html = f"""
      <div style="font-family:system-ui,sans-serif;max-width:420px">
        <p>Код для смены пароля:</p>
        <p style="font-size:32px;font-weight:700;letter-spacing:6px;margin:16px 0">{code}</p>
        <p style="color:#64748b">Код действует {ttl} минут.</p>
        <p style="color:#64748b">
          Если вы не запрашивали смену пароля — просто проигнорируйте это письмо,
          пароль останется прежним.
        </p>
      </div>
    """

    if not is_configured():
        if settings.APP_ENV.lower() == "prod":
            raise EmailNotConfiguredError(
                "SMTP не настроен: письмо с кодом отправить невозможно"
            )
        logger.warning(
            "SMTP не настроен — письмо не отправлено. Код смены пароля для %s: %s "
            "(так работает только dev; задайте SMTP_* в .env)",
            to,
            code,
        )
        return

    await send_email(to=to, subject=subject, text=text, html=html)


async def send_invitation(*, to: str, invitation_url: str, expires_hours: int) -> None:
    """Отправляет одноразовую ссылку для установки пароля."""
    subject = "Приглашение в СИГМУ"
    text = (
        "Вас пригласили в СИГМУ.\n\n"
        f"Чтобы задать пароль и войти, откройте ссылку:\n{invitation_url}\n\n"
        f"Ссылка действует {expires_hours} ч. Если вы не ожидали приглашение, "
        "просто проигнорируйте письмо."
    )
    html = f"""
      <div style="font-family:system-ui,sans-serif;max-width:520px">
        <h2>Вас пригласили в СИГМУ</h2>
        <p>Задайте пароль, чтобы активировать учётную запись.</p>
        <p style="margin:24px 0">
          <a href="{invitation_url}" style="background:#2563eb;color:#fff;padding:12px 18px;border-radius:8px;text-decoration:none">
            Принять приглашение
          </a>
        </p>
        <p style="color:#64748b">Ссылка действует {expires_hours} ч.</p>
        <p style="color:#64748b">Если вы не ожидали приглашение — проигнорируйте письмо.</p>
      </div>
    """

    if not is_configured():
        if settings.APP_ENV.lower() == "prod":
            raise EmailNotConfiguredError("SMTP не настроен: приглашение отправить невозможно")
        logger.warning(
            "SMTP не настроен — приглашение для %s не отправлено. Dev-ссылка: %s",
            to,
            invitation_url,
        )
        return

    await send_email(to=to, subject=subject, text=text, html=html)
