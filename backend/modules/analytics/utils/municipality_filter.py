"""Shared municipality filters for analytics read queries."""
from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy import and_, func, or_

from backend.db.comment_analysis import CommentAnalysis
from backend.db.publics import Public
from backend.modules.organization.municipalities import (
    KRASNOYARSK_MUNICIPALITIES,
    canonical_municipality_name,
    normalize_municipality,
)


def canonicalize_municipality_filter(value: str | None) -> str | None:
    """Каноническое название округа; на неизвестном значении бросает ValueError."""

    raw = (value or "").strip()
    if not raw:
        return None
    canonical = canonical_municipality_name(raw)
    if canonical is None:
        raise ValueError("Невалидный муниципалитет")
    return canonical


def canonicalize_municipality_filters(value: str | None) -> tuple[str, ...]:
    """Канонические названия округов из строки «Абанский округ,Канский округ».

    Порядок сохраняется, повторы убираются. Одно неизвестное название — ошибка
    на весь фильтр: молча отбросить его значило бы показать чужую территорию.
    """

    names: list[str] = []
    for chunk in (value or "").split(","):
        canonical = canonicalize_municipality_filter(chunk)
        if canonical is not None and canonical not in names:
            names.append(canonical)
    return tuple(names)


def municipality_aliases(value: str | None) -> tuple[str, ...]:
    """Синонимы названий: как их отдаёт геокодер и как они заданы у площадок.

    Для нескольких округов синонимы объединяются — запрос отбирает их разом.
    """

    aliases: set[str] = set()
    for canonical in canonicalize_municipality_filters(value):
        aliases.add(normalize_municipality(canonical))
        for option in KRASNOYARSK_MUNICIPALITIES:
            if option.label == canonical:
                aliases.update(option.keys)
                break
    return tuple(sorted((alias for alias in aliases if alias), key=len, reverse=True))


def _normalized_sql_text(*parts):
    return func.replace(func.lower(func.concat_ws(" ", *parts)), "ё", "е")


def _regexp_for_aliases(aliases: Iterable[str]) -> str:
    escaped = []
    for alias in aliases:
        value = re.escape(alias).replace(r"\ ", r"[[:space:]-]+")
        if value:
            escaped.append(value)
    if not escaped:
        return r"a^"
    return r"(^|[^[:alnum:]_а-яА-Я])(" + "|".join(escaped) + r")([^[:alnum:]_а-яА-Я]|$)"


def address_municipality_match_expr(municipality_name: str | None):
    """Условие SQLAlchemy для сопоставления округа, выведенного из адреса."""

    aliases = municipality_aliases(municipality_name)
    if not aliases:
        return None
    text_expr = _normalized_sql_text(
        func.json_extract_path_text(CommentAnalysis.entities, "address_hierarchy", "municipality"),
        func.json_extract_path_text(CommentAnalysis.entities, "address_hierarchy", "district"),
        func.json_extract_path_text(CommentAnalysis.entities, "address_hierarchy", "locality"),
        func.json_extract_path_text(CommentAnalysis.entities, "address"),
        func.json_extract_path_text(CommentAnalysis.hierarchy, "case"),
    )
    return text_expr.op("~")(_regexp_for_aliases(aliases))


def comment_municipality_filter_expr(municipality_name: str | None):
    """Отбирает комментарии по выбранному округу.

    Адресные сопоставляются по address и address_hierarchy, остальные — по
    округу, заданному импортированной площадке.
    """

    address_match = address_municipality_match_expr(municipality_name)
    if address_match is None:
        return None
    has_address = or_(
        func.coalesce(func.json_extract_path_text(CommentAnalysis.entities, "address"), "") != "",
        func.coalesce(func.json_extract_path_text(CommentAnalysis.hierarchy, "case"), "") != "",
        func.json_extract_path(CommentAnalysis.entities, "address_hierarchy").is_not(None),
    )
    public_match = _normalized_sql_text(Public.municipality_name).op("~")(
        _regexp_for_aliases(municipality_aliases(municipality_name))
    )
    return or_(
        and_(has_address, address_match),
        and_(~has_address, public_match),
    )


def public_municipality_filter_expr(municipality_name: str | None):
    aliases = municipality_aliases(municipality_name)
    if not aliases:
        return None
    return _normalized_sql_text(Public.municipality_name).op("~")(
        _regexp_for_aliases(aliases)
    )


def apply_comment_municipality_filter(query, municipality_name: str | None):
    expr = comment_municipality_filter_expr(municipality_name)
    return query if expr is None else query.where(expr)


def apply_public_municipality_filter(query, municipality_name: str | None):
    expr = public_municipality_filter_expr(municipality_name)
    return query if expr is None else query.where(expr)


def apply_address_municipality_filter(query, municipality_name: str | None):
    expr = address_municipality_match_expr(municipality_name)
    return query if expr is None else query.where(expr)


def raw_address_municipality_clause() -> str:
    return """
      AND (
          CAST(:municipality_pattern AS text) IS NULL
          OR replace(lower(concat_ws(
              ' ',
              json_extract_path_text(ca.entities,'address_hierarchy','municipality'),
              json_extract_path_text(ca.entities,'address_hierarchy','district'),
              json_extract_path_text(ca.entities,'address_hierarchy','locality'),
              json_extract_path_text(ca.entities,'address'),
              json_extract_path_text(ca.hierarchy,'case')
          )), 'ё', 'е') ~ CAST(:municipality_pattern AS text)
      )
    """


def raw_comment_municipality_clause() -> str:
    return """
      AND (
          CAST(:municipality_pattern AS text) IS NULL
          OR (
              (
                  coalesce(json_extract_path_text(ca.entities,'address'), '') <> ''
                  OR coalesce(json_extract_path_text(ca.hierarchy,'case'), '') <> ''
                  OR json_extract_path(ca.entities,'address_hierarchy') IS NOT NULL
              )
              AND replace(lower(concat_ws(
                  ' ',
                  json_extract_path_text(ca.entities,'address_hierarchy','municipality'),
                  json_extract_path_text(ca.entities,'address_hierarchy','district'),
                  json_extract_path_text(ca.entities,'address_hierarchy','locality'),
                  json_extract_path_text(ca.entities,'address'),
                  json_extract_path_text(ca.hierarchy,'case')
              )), 'ё', 'е') ~ CAST(:municipality_pattern AS text)
          )
          OR (
              coalesce(json_extract_path_text(ca.entities,'address'), '') = ''
              AND coalesce(json_extract_path_text(ca.hierarchy,'case'), '') = ''
              AND json_extract_path(ca.entities,'address_hierarchy') IS NULL
              AND replace(lower(coalesce(p.municipality_name, '')), 'ё', 'е') ~ CAST(:municipality_public_name AS text)
          )
      )
    """


def raw_municipality_params(municipality_name: str | None) -> dict[str, str | None]:
    names = canonicalize_municipality_filters(municipality_name)
    if not names:
        return {"municipality_pattern": None, "municipality_public_name": None}
    # Точное совпадение по названию площадки, но округов может быть несколько,
    # поэтому вместо равенства — якорный перечень.
    exact = "|".join(re.escape(normalize_municipality(name)) for name in names)
    return {
        "municipality_pattern": _regexp_for_aliases(municipality_aliases(municipality_name)),
        "municipality_public_name": f"^({exact})$",
    }
