"""Разбор таблицы площадок и валидация строк импорта."""
import io

import pytest
from fastapi import HTTPException

from backend.modules.organization.services.public_import_service import (
    PublicImportService,
    dedup_key,
    normalize_url,
    social_network_code,
)


def parse(text: str, filename: str = "publics.csv") -> list[dict[str, str]]:
    return PublicImportService._parse(text.encode("utf-8-sig"), filename)


def validate(rows, *, existing=frozenset()):
    seen: set[str] = set()
    existing_urls = set(existing)
    return [
        PublicImportService._validate_row(
            index, row, existing_urls=existing_urls, seen_urls=seen
        )
        for index, row in enumerate(rows, start=2)
    ]


# ── заголовки ───────────────────────────────────────────────────────────────


def test_russian_headers():
    rows = parse("название паблика;ссылка\nАдминистрация;https://vk.com/krsk")
    assert rows == [{"name": "Администрация", "url": "https://vk.com/krsk"}]


def test_latin_headers():
    rows = parse("name;url\nАдминистрация;https://vk.com/krsk")
    assert rows == [{"name": "Администрация", "url": "https://vk.com/krsk"}]


def test_comma_delimiter():
    rows = parse("название,ссылка\nЦентр,https://vk.com/centr")
    assert rows == [{"name": "Центр", "url": "https://vk.com/centr"}]


def test_without_header():
    """Колонка со ссылками определяется по содержимому первой строки."""
    rows = parse("Администрация;vk.com/krsk\nМолодёжка;ok.ru/group/700")
    assert [r["name"] for r in rows] == ["Администрация", "Молодёжка"]
    assert [r["url"] for r in rows] == ["vk.com/krsk", "ok.ru/group/700"]


def test_url_only_column():
    rows = parse("https://vk.com/one\nhttps://ok.ru/group/2")
    assert [r["url"] for r in rows] == ["https://vk.com/one", "https://ok.ru/group/2"]


def test_blank_lines_ignored():
    rows = parse("название;ссылка\n\nЦентр;https://vk.com/centr\n;\n")
    assert rows == [{"name": "Центр", "url": "https://vk.com/centr"}]


def test_xlsx_with_russian_headers():
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["название паблика", "ссылка"])
    sheet.append(["Администрация", "https://vk.com/krsk"])
    sheet.append([None, None])
    sheet.append(["Молодёжка", "ok.ru/group/700"])

    buffer = io.BytesIO()
    workbook.save(buffer)

    rows = PublicImportService._parse(buffer.getvalue(), "publics.xlsx")
    assert rows == [
        {"name": "Администрация", "url": "https://vk.com/krsk"},
        {"name": "Молодёжка", "url": "ok.ru/group/700"},
    ]


def test_table_without_links_rejected():
    with pytest.raises(HTTPException) as exc:
        parse("Администрация;отдел культуры\nМолодёжка;отдел спорта")
    assert exc.value.status_code == 400


def test_unsupported_extension():
    with pytest.raises(HTTPException) as exc:
        parse("name;url", filename="publics.txt")
    assert exc.value.status_code == 400


# ── нормализация ссылок ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("vk.com/krsk", "https://vk.com/krsk"),
        ("https://m.vk.com/Krsk/", "https://vk.com/Krsk"),
        ("https://vk.com/krsk?w=wall-1_2", "https://vk.com/krsk"),
        ("www.ok.ru/group/700", "https://ok.ru/group/700"),
        ("мусор", None),
        ("", None),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


def test_dedup_key_ignores_case():
    """Регистр пути сохраняется для API, но дубликаты ищутся без него."""
    assert dedup_key(normalize_url("https://ok.ru/GroupName")) == dedup_key(
        normalize_url("https://ok.ru/groupname")
    )


def test_social_network_code():
    assert social_network_code("https://vk.com/krsk") == "vk"
    assert social_network_code("https://ok.ru/group/700") == "ok"
    assert social_network_code("https://t.me/chan") == "telegram"


# ── валидация строк ─────────────────────────────────────────────────────────


def test_row_without_url_is_error():
    (row,) = validate([{"name": "Центр", "url": ""}])
    assert row.status == "error"
    assert row.errors == ["Не указана ссылка"]


def test_telegram_network_is_supported():
    (row,) = validate([{"name": "Канал", "url": "https://t.me/chan"}])
    assert row.status == "create"
    assert row.url == "https://t.me/chan"


def test_social_network_home_page_is_error():
    (row,) = validate([{"name": "", "url": "https://vk.com"}])
    assert row.status == "error"


def test_duplicate_inside_file():
    rows = validate(
        [
            {"name": "Первый", "url": "vk.com/krsk"},
            {"name": "Он же", "url": "https://M.VK.com/Krsk/"},
        ]
    )
    assert [r.status for r in rows] == ["create", "error"]
    assert rows[1].errors == ["Дубликат ссылки внутри файла"]


def test_existing_public_is_skipped():
    (row,) = validate(
        [{"name": "Центр", "url": "vk.com/centr"}],
        existing={"https://vk.com/centr"},
    )
    assert row.status == "skip"
    assert row.warnings == ["Площадка уже есть в организации"]


def test_missing_name_only_warns():
    (row,) = validate([{"name": "", "url": "https://vk.com/krsk"}])
    assert row.status == "create"
    assert row.warnings == ["Название будет взято из соцсети"]
    assert row.url == "https://vk.com/krsk"


# ── защита от подмены статусов клиентом ─────────────────────────────────────


def test_revalidate_rejects_forged_rows():
    from backend.modules.organization.schemas import PublicImportRowPreview
    from backend.modules.organization.services.public_import_runner import revalidate

    forged = PublicImportRowPreview(
        row_number=2, status="create", name="Чужое", url="https://example.com/chan"
    )
    honest = PublicImportRowPreview(
        row_number=3, status="create", name="Центр", url="https://vk.com/centr"
    )

    checked = revalidate([forged, honest])
    assert [r.status for r in checked] == ["error", "create"]
