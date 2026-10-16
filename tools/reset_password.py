"""Аварийная смена пароля пользователя напрямую в БД.

Нужен, когда войти нельзя вообще: почта не настроена, кода не дождаться,
а администратор один и пароль забыт. Обычный путь пользователя — форма
«Забыли пароль?», она шлёт код на почту.

Запуск:
    python -m tools.reset_password --list
    python -m tools.reset_password --email user@example.ru
    python -m tools.reset_password --email user@example.ru --password 'новый'
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from backend.db.database import async_session_maker
from backend.db.users import User
from backend.modules.auth.services.password_service import PasswordService

MIN_LENGTH = 8


async def list_users() -> int:
    async with async_session_maker() as db:
        users = (await db.execute(select(User).order_by(User.email))).scalars().all()

    if not users:
        print("В базе нет ни одного пользователя.")
        return 1

    for user in users:
        print(f"{user.email:40} {user.role.value if user.role else '—':12} {user.status.value}")
    return 0


async def reset(email: str, password: str) -> int:
    async with async_session_maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"Пользователь {email} не найден. Список: --list")
            return 1

        user.password_hash = PasswordService().hash_password(password)
        await db.commit()

    print(f"Пароль для {email} изменён.")
    return 0


def ask_password() -> str | None:
    """Спрашивает пароль дважды, не показывая ввод."""
    first = getpass.getpass("Новый пароль: ")
    if len(first) < MIN_LENGTH:
        print(f"Пароль короче {MIN_LENGTH} символов.")
        return None
    if first != getpass.getpass("Повторите: "):
        print("Пароли не совпали.")
        return None
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email")
    parser.add_argument("--password", help="без него пароль спросят скрытым вводом")
    parser.add_argument("--list", action="store_true", help="показать пользователей")
    args = parser.parse_args(argv)

    if args.list:
        return asyncio.run(list_users())

    if not args.email:
        parser.error("нужен --email или --list")

    password = args.password or ask_password()
    if password is None:
        return 1
    if len(password) < MIN_LENGTH:
        print(f"Пароль короче {MIN_LENGTH} символов.")
        return 1

    return asyncio.run(reset(args.email.strip().lower(), password))


if __name__ == "__main__":
    sys.exit(main())
