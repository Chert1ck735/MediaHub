"""Ключи Яндекс-геокодера на проде: посмотреть расход и заменить список.

Ключи хранятся в БД, а не в `.env`: на сервере правка переменных требует
передеплоя, а ключи меняются по мере выборки суточной нормы. Пул перебирает их
по порядку и при отказе переходит к следующему.

Запуск (пароль спрашивается при входе, токен нигде не сохраняется):

    python -m tools.geo_keys_cli --base-url https://sigma.krskcit.ru --email me@krskcit.ru
    python -m tools.geo_keys_cli --base-url https://sigma.krskcit.ru --email me@krskcit.ru \\
        --set ключ-1,ключ-2,ключ-3
"""
from __future__ import annotations

import argparse
import getpass

import httpx


def _client(base_url: str, email: str) -> tuple[httpx.Client, dict[str, str]]:
    password = getpass.getpass(f"Пароль для {email}: ")
    client = httpx.Client(base_url=base_url.rstrip("/"), timeout=60)
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    token = response.json()["access_token"]
    return client, {"Authorization": f"Bearer {token}"}


def _show(usage: dict) -> None:
    keys = usage.get("keys") or []
    if not keys:
        print("Ключи не заданы — геокодер работает на значении из .env либо молчит.")
        return
    print(f"дата {usage.get('date')}, норма на ключ {usage.get('budget_per_key')}")
    print(f"  {'ключ':>12}  {'израсходовано':>13}  {'остаток':>8}  состояние")
    for row in keys:
        state = "отклонён до конца суток" if row.get("blocked") else "рабочий"
        print(f"  {row.get('key'):>12}  {row.get('used'):>13}  {row.get('left'):>8}  {state}")
    total = sum(row.get("left") or 0 for row in keys if not row.get("blocked"))
    print(f"\nдоступно запросов сегодня: {total}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="адрес прода")
    parser.add_argument("--email", required=True, help="аккаунт для входа")
    parser.add_argument("--set", dest="keys", help="новый список ключей через запятую")
    args = parser.parse_args()

    client, headers = _client(args.base_url, args.email)
    with client:
        if args.keys:
            keys = [key.strip() for key in args.keys.split(",") if key.strip()]
            response = client.put("/api/analytics/geo-keys", json={"keys": keys}, headers=headers)
            response.raise_for_status()
            print(f"Сохранено ключей: {len(keys)}\n")
            _show(response.json())
        else:
            response = client.get("/api/analytics/geo-keys", headers=headers)
            response.raise_for_status()
            _show(response.json())


if __name__ == "__main__":
    main()
