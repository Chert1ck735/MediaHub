import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from backend.db import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASS}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)


config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


INITIAL_REVISION = "f3410cd5e9c7"


def _auto_stamp_legacy_db(connection) -> None:
    """Авто-stamp init-ревизии для legacy окружений.

    На многих окружениях схема была создана через `Base.metadata.create_all`
    (а не через alembic). Признак: `alembic_version` отсутствует, но
    `organizations` уже существует. В этом случае мы НЕ накатываем init заново
    (это упадёт на дубликате таблиц), а просто помечаем init как уже
    применённый. Дальше обычные migrations поедут с него.
    """
    from sqlalchemy import inspect, text
    inspector = inspect(connection)
    if inspector.has_table("alembic_version"):
        return
    if not inspector.has_table("organizations"):
        return  # совсем чистая БД, обычный upgrade накатит всё
    print(
        f"[alembic] alembic_version отсутствует, но organizations есть — "
        f"auto-stamp '{INITIAL_REVISION}' (legacy create_all)"
    )
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS alembic_version "
        "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
    ))
    connection.execute(text(
        f"INSERT INTO alembic_version (version_num) VALUES ('{INITIAL_REVISION}') "
        f"ON CONFLICT (version_num) DO NOTHING"
    ))


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Перед запуском миграций проверяем legacy-случай и автоматически
        # stamp'aем init-ревизию, если БД создавалась через create_all.
        _auto_stamp_legacy_db(connection)
        connection.commit()

        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

print("MODELS LOADED")
print(Base.metadata.tables.keys())
