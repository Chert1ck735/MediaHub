"""Массовый импорт площадок из таблицы: preview → confirm.

Файл содержит две колонки — название площадки и ссылку. Заголовки понимаются
как русские («название паблика», «ссылка»), так и латинские (``name``, ``url``);
файл без заголовка тоже принимается — тогда колонки читаются по позиции.

Правила:
* ссылка обязательна, схему ``https://`` можно не писать;
* поддерживаются vk.com, ok.ru и t.me/telegram.me — остальные домены отбраковываются;
* название опционально: настоящее имя площадки берётся из API соцсети;
* дубликаты ищутся по нормализованной ссылке без учёта регистра;
* ошибочная строка не отменяет остальные.

Создание площадок вынесено в ``public_import_runner``: каждая строка проходит
тот же ingest, что и ручное добавление ссылки, поэтому у площадки сразу
правильное имя, ``external_public_id`` и метрики.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from typing import Iterable
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import Public, PublicSocialLink
from backend.db.users import User
from backend.modules.organization.schemas import (
    PublicImportPreviewResponse,
    PublicImportRowPreview,
)
from backend.modules.organization.services.authorization_service import AuthorizationService

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 МБ
MAX_ROWS = 5_000

# Как могут называться колонки в реальных таблицах.
NAME_ALIASES = {
    "name",
    "title",
    "название",
    "название паблика",
    "название площадки",
    "наименование",
    "паблик",
    "площадка",
    "сообщество",
    "группа",
}
URL_ALIASES = {
    "url",
    "link",
    "ссылка",
    "ссылка на паблик",
    "ссылка на площадку",
    "ссылка на группу",
    "адрес",
}

SUPPORTED_HOSTS = {
    "vk.com": "vk",
    "ok.ru": "ok",
    "t.me": "telegram",
    "telegram.me": "telegram",
}

_HOST_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$")


def normalize_url(raw: str) -> str | None:
    """Приводит ссылку к каноничному виду или возвращает None, если это не ссылка.

    Регистр пути сохраняется: короткое имя группы уходит в ``group.getInfo``
    как есть. Для поиска дублей есть ``dedup_key``.
    """
    value = (raw or "").strip()
    if not value:
        return None

    if "://" not in value:
        value = f"https://{value}"

    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        return None

    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    for prefix in ("www.", "m.", "new."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    if not host or not _HOST_RE.match(host):
        return None

    return f"https://{host}{parts.path.rstrip('/')}"


def dedup_key(normalized_url: str) -> str:
    """Ключ сравнения ссылок: vk.com/Krsk и vk.com/krsk — одна площадка."""
    return normalized_url.lower()


def _cell(row: list[str], index: int | None) -> str:
    """Значение колонки строки; пусто, если колонки нет."""
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def social_network_code(normalized_url: str) -> str | None:
    """Код соцсети по нормализованной ссылке; None — сеть не поддерживается."""
    host = urlsplit(normalized_url).netloc.lower()
    return SUPPORTED_HOSTS.get(host)


class PublicImportService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._authz = AuthorizationService(db)

    # ── разбор файла ────────────────────────────────────────────────────────

    @staticmethod
    def _parse(content: bytes, filename: str) -> list[dict[str, str]]:
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"Файл больше {MAX_FILE_BYTES // 1024 // 1024} МБ",
            )

        name = (filename or "").lower()
        if name.endswith(".csv"):
            table = PublicImportService._read_csv(content)
        elif name.endswith(".xlsx"):
            table = PublicImportService._read_xlsx(content)
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Поддерживаются только файлы .xlsx и .csv",
            )

        rows = PublicImportService._to_rows(table)
        if len(rows) > MAX_ROWS:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"В файле больше {MAX_ROWS} строк",
            )
        return rows

    @staticmethod
    def _read_csv(content: bytes) -> list[list[str]]:
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Не удалось прочитать кодировку CSV"
            )

        first_line = text.split("\n", 1)[0]
        delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","

        return [
            [(cell or "").strip() for cell in row]
            for row in csv.reader(io.StringIO(text), delimiter=delimiter)
        ]

    @staticmethod
    def _read_xlsx(content: bytes) -> list[list[str]]:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            sheet = workbook.active
            return [
                ["" if cell is None else str(cell).strip() for cell in values]
                for values in sheet.iter_rows(values_only=True)
            ]
        finally:
            workbook.close()

    @staticmethod
    def _to_rows(table: list[list[str]]) -> list[dict[str, str]]:
        """Раскладывает таблицу по полям name/url.

        Заголовок распознаётся по алиасам. Если его нет — колонки определяются
        по содержимому: та, где лежат ссылки, считается url, соседняя — name.
        """
        rows = [row for row in table if any((cell or "").strip() for cell in row)]
        if not rows:
            return []

        header = [(cell or "").strip().lower() for cell in rows[0]]
        name_index = next(
            (i for i, cell in enumerate(header) if cell in NAME_ALIASES), None
        )
        url_index = next(
            (i for i, cell in enumerate(header) if cell in URL_ALIASES), None
        )

        if url_index is None and name_index is None:
            # Заголовка нет: ищем колонку со ссылками по первой строке данных.
            url_index = next(
                (i for i, cell in enumerate(rows[0]) if normalize_url(cell)), None
            )
            if url_index is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Не нашёл колонку со ссылками. Ожидаются колонки "
                    "«название паблика» и «ссылка» (или name и url).",
                )
            name_index = 0 if url_index != 0 else (1 if len(rows[0]) > 1 else None)
            data_rows = rows
        else:
            if url_index is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "В заголовке нет колонки со ссылкой («ссылка» или url).",
                )
            data_rows = rows[1:]

        return [
            {
                "name": _cell(row, name_index),
                "url": _cell(row, url_index),
            }
            for row in data_rows
        ]

    # ── preview ─────────────────────────────────────────────────────────────

    async def preview(
        self,
        actor: User,
        organization_id: uuid.UUID,
        content: bytes,
        filename: str,
    ) -> PublicImportPreviewResponse:
        self._authz.require_organization_admin(actor, organization_id)

        raw_rows = self._parse(content, filename)
        if not raw_rows:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файл пуст")

        existing_urls = await self._existing_urls(organization_id)

        rows: list[PublicImportRowPreview] = []
        seen_urls: set[str] = set()
        for index, raw in enumerate(raw_rows, start=2):
            rows.append(
                self._validate_row(
                    index, raw, existing_urls=existing_urls, seen_urls=seen_urls
                )
            )

        return PublicImportPreviewResponse(
            rows=rows,
            to_create=sum(1 for r in rows if r.status == "create"),
            skipped=sum(1 for r in rows if r.status == "skip"),
            errors=sum(1 for r in rows if r.status == "error"),
        )

    async def _existing_urls(self, organization_id: uuid.UUID) -> set[str]:
        """Ключи сравнения для ссылок площадок организации."""
        result = await self._db.execute(
            select(PublicSocialLink.url).where(
                PublicSocialLink.public.has(Public.organization_id == organization_id)
            )
        )
        keys = set()
        for url in result.scalars().all():
            normalized = normalize_url(url or "")
            if normalized:
                keys.add(dedup_key(normalized))
        return keys

    @staticmethod
    def _validate_row(
        row_number: int,
        raw: dict[str, str],
        *,
        existing_urls: set[str],
        seen_urls: set[str],
    ) -> PublicImportRowPreview:
        name = (raw.get("name") or "").strip()
        raw_url = (raw.get("url") or "").strip()
        normalized = normalize_url(raw_url)

        def row(status_: str, *, url: str | None, errors=(), warnings=()):
            return PublicImportRowPreview(
                row_number=row_number,
                status=status_,
                name=name or None,
                url=url,
                errors=list(errors),
                warnings=list(warnings),
            )

        if not raw_url:
            return row("error", url=None, errors=["Не указана ссылка"])
        if normalized is None:
            return row("error", url=raw_url, errors=[f"Некорректная ссылка: {raw_url}"])

        network = social_network_code(normalized)
        if network is None:
            return row(
                "error",
                url=normalized,
                errors=["Поддерживаются только ссылки на vk.com, ok.ru и t.me"],
            )
        if not urlsplit(normalized).path.strip("/"):
            return row(
                "error",
                url=normalized,
                errors=["Ссылка ведёт на главную страницу соцсети, а не на площадку"],
            )

        key = dedup_key(normalized)
        if key in seen_urls:
            return row("error", url=normalized, errors=["Дубликат ссылки внутри файла"])
        if key in existing_urls:
            return row(
                "skip", url=normalized, warnings=["Площадка уже есть в организации"]
            )

        seen_urls.add(key)
        warnings = [] if name else ["Название будет взято из соцсети"]
        return row("create", url=normalized, warnings=warnings)

    # ── шаблон и отчёт ──────────────────────────────────────────────────────

    @staticmethod
    def build_error_report(rows: Iterable[PublicImportRowPreview]) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(["Строка", "название паблика", "ссылка", "Ошибки"])
        for row in rows:
            if row.status != "error":
                continue
            writer.writerow(
                [row.row_number, row.name or "", row.url or "", " | ".join(row.errors)]
            )
        return buffer.getvalue().encode("utf-8-sig")

    @staticmethod
    def build_template() -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(["название паблика", "ссылка"])
        writer.writerow(["Городская администрация", "https://vk.com/digitalkrsk24"])
        writer.writerow(["Молодёжный центр", "https://ok.ru/group/70000000000000"])
        return buffer.getvalue().encode("utf-8-sig")
