"""Сравнение SQLAlchemy-моделей с фактической схемой PostgreSQL.

Зачем: перед prod-деплоем нужно знать, не разъехались ли модели и БД.
- Колонка есть в модели, но нет в БД → следующая alembic-миграция её
  создаст; ничего не сломается, но факт зафиксировать.
- Колонка есть в БД, но нет в модели → orphan. Не критично, но в
  rebuild_*_snapshot её никто не читает; либо описать в модели, либо
  убрать миграцией.
- Таблица в моделях, но не в БД → миграция не накатана, рантайм упадёт.
- Таблица в БД, но не в моделях → legacy / создана вручную (через
  create_all без модели). Опасно: alembic её не видит.
- Type mismatch (varchar vs text, int vs bigint) → скрытая бага при
  записи больших значений.

Запуск:
    python tools/schema_drift.py
    python tools/schema_drift.py --fail-on-drift   # exit 1 если что-то найдено

Чистый запуск (нет drift) → exit 0. Подходит для CI pipeline.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ленивые импорты после sys.path
from dotenv import load_dotenv  # noqa: E402
load_dotenv(PROJECT_ROOT / ".env")

import psycopg2  # noqa: E402

# Импорт всех моделей нужен, чтобы Base.metadata.tables был заполнен.
# Любой новый модельный модуль должен быть включён в backend/db/__init__.py,
# иначе drift-скрипт его не увидит — это ожидаемое поведение, оно подсветит
# забытую регистрацию модели.
import backend.db  # noqa: F401, E402
from backend.db.base import Base  # noqa: E402

# Таблицы, которые мы НЕ хотим видеть в drift-репорте, потому что они
# управляются другими инструментами (не SQLAlchemy-моделями).
IGNORED_DB_TABLES: frozenset[str] = frozenset({
    "alembic_version",  # alembic метаданные
    "spatial_ref_sys",  # PostGIS, если кто-то поставил
    "pg_stat_statements",  # расширение
})


@dataclass
class TableDrift:
    name: str
    only_in_db: list[str] = field(default_factory=list)        # колонки в БД, нет в модели
    only_in_model: list[str] = field(default_factory=list)     # колонки в модели, нет в БД
    type_mismatches: list[tuple[str, str, str]] = field(default_factory=list)
    # (column_name, model_type, db_type) — для type mismatch

    @property
    def is_clean(self) -> bool:
        return not (self.only_in_db or self.only_in_model or self.type_mismatches)


@dataclass
class SchemaReport:
    tables_only_in_db: list[str] = field(default_factory=list)
    tables_only_in_model: list[str] = field(default_factory=list)
    per_table: list[TableDrift] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        if self.tables_only_in_db or self.tables_only_in_model:
            return True
        return any(not t.is_clean for t in self.per_table)


# ---- Извлечение из моделей ----

def _model_columns(table) -> dict[str, str]:
    """Имя колонки -> упрощённый строковый тип для diff."""
    out: dict[str, str] = {}
    for col in table.columns:
        out[col.name] = _normalize_model_type(col.type)
    return out


def _normalize_model_type(sql_type) -> str:
    """Свести разные представления типов к строке для сравнения.

    Точное сравнение типов SQLAlchemy<->PostgreSQL — тяжёлая задача
    (диалекты, enums, server-side defaults), поэтому здесь сознательно
    грубая нормализация: важна семантика (varchar vs int), не длина.
    """
    raw = str(sql_type).upper()
    if raw.startswith("VARCHAR"):
        return "varchar"
    if raw.startswith("CHAR"):
        return "char"
    if "TEXT" in raw:
        return "text"
    if raw == "UUID" or "UUID(" in raw:
        return "uuid"
    if "BIGINT" in raw or raw == "BIGSERIAL":
        return "bigint"
    if raw == "INTEGER" or raw == "INT" or raw == "SERIAL":
        return "integer"
    if "SMALLINT" in raw:
        return "smallint"
    if "TIMESTAMP" in raw or "DATETIME" in raw:
        # SQLAlchemy DateTime(timezone=True/False) — оба маппятся в PG
        # timestamp[tz]. Тут сводим к одному.
        return "timestamp"
    if raw == "DATE":
        return "date"
    if raw == "BOOLEAN" or raw == "BOOL":
        return "boolean"
    if "FLOAT" in raw or "DOUBLE" in raw or "REAL" in raw:
        return "float"
    if raw == "NUMERIC" or raw.startswith("NUMERIC("):
        return "numeric"
    if "JSONB" in raw:
        return "jsonb"
    if "JSON" in raw:
        return "json"
    if raw.startswith("ENUM"):
        return "enum"
    return raw.lower()


# ---- Извлечение из БД ----

def _db_tables_and_columns(conn) -> dict[str, dict[str, str]]:
    """{table_name: {column_name: pg_type}} только для BASE TABLE (не VIEW).

    Views в drift не интересны: они описаны DDL'ом в init-миграции, не
    маппятся на SQLAlchemy-модели. Если попытаемся "починить" их через
    модели — устроим бардак.
    """
    cur = conn.cursor()
    cur.execute("""
        select c.table_name, c.column_name, c.data_type, c.udt_name
        from information_schema.columns c
        join information_schema.tables t
          on t.table_schema = c.table_schema
         and t.table_name   = c.table_name
        where c.table_schema = 'public'
          and t.table_type   = 'BASE TABLE'
        order by c.table_name, c.ordinal_position
    """)
    out: dict[str, dict[str, str]] = {}
    for table, col, data_type, udt in cur.fetchall():
        out.setdefault(table, {})[col] = _normalize_db_type(data_type, udt)
    cur.close()
    return out


def _normalize_db_type(data_type: str, udt_name: str) -> str:
    dt = data_type.lower()
    udt = (udt_name or "").lower()
    if udt == "uuid":
        return "uuid"
    if dt.startswith("character varying"):
        return "varchar"
    if dt == "character":
        return "char"
    if dt == "text":
        return "text"
    if dt == "bigint":
        return "bigint"
    if dt == "integer":
        return "integer"
    if dt == "smallint":
        return "smallint"
    if "timestamp" in dt:
        return "timestamp"
    if dt == "date":
        return "date"
    if dt == "boolean":
        return "boolean"
    if dt in ("double precision", "real"):
        return "float"
    if dt == "numeric":
        return "numeric"
    if dt == "jsonb":
        return "jsonb"
    if dt == "json":
        return "json"
    if dt.startswith("user-defined"):
        return "enum"
    return dt


# ---- Diff ----

def build_report(model_tables: dict[str, dict[str, str]], db_tables: dict[str, dict[str, str]]) -> SchemaReport:
    report = SchemaReport()

    model_names = set(model_tables)
    db_names = set(db_tables) - IGNORED_DB_TABLES

    report.tables_only_in_db = sorted(db_names - model_names)
    report.tables_only_in_model = sorted(model_names - db_names)

    for tname in sorted(model_names & db_names):
        model_cols = model_tables[tname]
        db_cols = db_tables[tname]
        drift = TableDrift(name=tname)
        drift.only_in_model = sorted(set(model_cols) - set(db_cols))
        drift.only_in_db = sorted(set(db_cols) - set(model_cols))
        for col in sorted(set(model_cols) & set(db_cols)):
            mt, dt = model_cols[col], db_cols[col]
            if mt != dt and not _types_equivalent(mt, dt):
                drift.type_mismatches.append((col, mt, dt))
        if not drift.is_clean:
            report.per_table.append(drift)
    return report


def _types_equivalent(model_type: str, db_type: str) -> bool:
    """Допускаем известные эквивалентности, чтобы не шуметь."""
    equivalents = (
        {"text", "varchar"},     # SQLAlchemy String/Text → varchar/text в PG
        {"enum", "varchar"},     # SQLAlchemy Enum → varchar если create_type=False
        {"json", "jsonb"},       # На проекте сознательно используется jsonb
        {"datetime", "timestamp"},
        {"timestamp", "timestamp with time zone"},
    )
    pair = {model_type, db_type}
    return any(pair <= eq for eq in equivalents)


# ---- Вывод ----

def render_report(report: SchemaReport) -> Iterable[str]:
    if report.tables_only_in_db:
        yield "ТАБЛИЦЫ ТОЛЬКО В БД (нет в моделях — orphan или legacy):"
        for t in report.tables_only_in_db:
            yield f"  - {t}"
        yield ""
    if report.tables_only_in_model:
        yield "ТАБЛИЦЫ ТОЛЬКО В МОДЕЛЯХ (нет в БД — миграция не накатана):"
        for t in report.tables_only_in_model:
            yield f"  - {t}"
        yield ""
    if report.per_table:
        yield "РАСХОЖДЕНИЯ ПО КОЛОНКАМ:"
        for drift in report.per_table:
            yield f"  [{drift.name}]"
            if drift.only_in_model:
                yield f"    + только в модели (не создано в БД): {', '.join(drift.only_in_model)}"
            if drift.only_in_db:
                yield f"    - только в БД (нет в модели, orphan?): {', '.join(drift.only_in_db)}"
            for col, mt, dt in drift.type_mismatches:
                yield f"    ! type mismatch '{col}': model={mt} vs db={dt}"
        yield ""
    if not report.has_drift:
        yield "OK: модели и БД совпадают."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-on-drift", action="store_true",
                        help="Завершить с exit code 1, если найдены расхождения (для CI)")
    args = parser.parse_args()

    db_name = os.getenv("DB_NAME")
    if not db_name:
        print("ERROR: DB_NAME не задан в .env")
        return 2

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=db_name,
    )
    try:
        db_tables = _db_tables_and_columns(conn)
    finally:
        conn.close()

    model_tables = {name: _model_columns(t) for name, t in Base.metadata.tables.items()}

    report = build_report(model_tables, db_tables)
    for line in render_report(report):
        print(line)

    if report.has_drift and args.fail_on_drift:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
