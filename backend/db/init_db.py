import asyncio
import os
import uuid

# Для инициализации схемы БД нужны только DB_* переменные.
# Остальные обязательные настройки приложения подставляем заглушками,
# чтобы init_db можно было запускать до полной настройки VK.
os.environ.setdefault("ACCESS_TOKEN", "init-db-placeholder")
os.environ.setdefault("GROUP_ID", "0")

from sqlalchemy import text

from backend.db.database import engine
from backend.db.schema_sync import ensure_runtime_schema
import backend.db  # noqa: F401

_SOCIAL_NETWORK_SEED = [
    ("vk", "VK", "ВКонтакте"),
    ("telegram", "Telegram", "Telegram"),
    ("dzen", "Дзен", "Дзен"),
    ("ok", "OK", "Одноклассники"),
    ("youtube", "YouTube", "YouTube"),
]


async def init_db() -> None:
    await ensure_runtime_schema(engine)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE organizations "
                "SET type = 'other' "
                "WHERE type::text = 'youth_center'"
            )
        )
        for code, name, description in _SOCIAL_NETWORK_SEED:
            await conn.execute(
                text(
                    """
                    INSERT INTO social_networks (id, code, name, description)
                    VALUES (:id, :code, :name, :description)
                    ON CONFLICT (code) DO UPDATE
                    SET name = EXCLUDED.name,
                        description = EXCLUDED.description
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "code": code,
                    "name": name,
                    "description": description,
                },
            )


def main() -> None:
    asyncio.run(init_db())


if __name__ == "__main__":
    main()
