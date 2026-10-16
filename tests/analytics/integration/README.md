# Интеграционные тесты analytics

Работают на **отдельной** тестовой БД (НЕ на рабочей `media_project`).
Фикстура `db_session` (`tests/conftest.py`) создаёт схему, наполняет данные
и чистит таблицы после каждого теста (`TRUNCATE ... CASCADE`).

## Разовая подготовка БД

```bash
# 1) создать отдельную тестовую базу
psql -U postgres -h localhost -c "CREATE DATABASE media_test;"

# 2) накатить схему (создаёт enum-типы + таблицы; нужно из-за create_type=False в моделях)
DB_NAME=media_test alembic upgrade head
```

## Запуск

URL тестовой БД берётся из `TEST_DATABASE_URL` (дефолт — `postgres:postgres@localhost/media_test`).
Локально, если пароль отличается:

```bash
set TEST_DATABASE_URL=postgresql+asyncpg://postgres:<пароль>@localhost:5432/media_test
pytest tests/analytics/integration -m integration
```

Тесты помечены маркером `integration` — их можно отдельно включать/исключать
(`-m integration` / `-m "not integration"`).
