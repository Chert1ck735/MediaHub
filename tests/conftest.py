import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

from backend.db import Base

# URL тестовой БД из окружения; дефолт прежний (на сервере поведение не меняется).
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/media_test",
)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Изолированная async-сессия на отдельной тестовой БД.

    Предохранитель: работаем, только если в имени БД есть ``test`` — чтобы
    truncate случайно не вычистил dev/prod-базу. Если БД недоступна —
    пропускаем тест (skip), а не валим билд.
    """
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0].lower()
    if "test" not in db_name:
        pytest.skip(
            "TEST_DATABASE_URL не похож на тестовую БД (нет 'test' в имени) — "
            "пропуск, чтобы не тронуть рабочую базу"
        )

    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"Тестовая БД недоступна, интеграционный тест пропущен: {exc}")

    SessionLocal = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )

    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        """
                        TRUNCATE TABLE
                            public_social_links,
                            publics,
                            social_networks,
                            users,
                            organizations
                        RESTART IDENTITY CASCADE
                        """
                    )
                )

    await engine.dispose()
