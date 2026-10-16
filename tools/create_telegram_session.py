"""Однократно создаёт TELEGRAM_SESSION_STRING через настроенный WPS-прокси.

Запускать на защищённой машине: строка сессии даёт доступ к Telegram-аккаунту.
Скрипт не читает .env намеренно — секреты передаются окружением и не попадают
в историю команд или в репозиторий.
"""

from __future__ import annotations

import asyncio
import os

from telethon import TelegramClient
from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyAbridged
from telethon.sessions import StringSession


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана переменная {name}")
    return value


async def main() -> None:
    api_id = int(_required("TELEGRAM_API_ID"))
    api_hash = _required("TELEGRAM_API_HASH")
    proxy = (
        _required("TELEGRAM_PROXY_HOST"),
        int(os.getenv("TELEGRAM_PROXY_PORT", "1443")),
        _required("TELEGRAM_PROXY_SECRET"),
    )
    client = TelegramClient(
        StringSession(),
        api_id,
        api_hash,
        connection=ConnectionTcpMTProxyAbridged,
        proxy=proxy,
    )
    await client.start()
    try:
        print("TELEGRAM_SESSION_STRING=" + StringSession.save(client.session))
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
