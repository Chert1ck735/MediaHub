"""Глобальные настройки приложения — простое key/value-хранилище.

Одна строка = одна настройка (ключ → строковое значение). Нужна там, где
значение должно править администратор в рантайме, а не через .env/перезапуск —
например период автопарсера. Значения храним строками и парсим на месте
чтения: таблица не знает про типы, зато остаётся универсальной.
"""

from backend.db.base import Base, TimestampMixin
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column


class AppSetting(Base, TimestampMixin):
    __tablename__ = "app_settings"

    # Ключ — сам по себе идентификатор строки (настроек немного, UUID тут лишний).
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
