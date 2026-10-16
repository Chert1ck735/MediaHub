"""Реестр инцидентов (лайт, derived): адресные кейсы как отслеживаемые задачи.

Инцидент = адресный кейс с жалобами. Организация — по маппингу категории,
статус — из наличия официального ответа (reaction-gap) и возраста относительно
последней даты в данных. Без своей таблицы: считается на лету из кейсов.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.users import User
from backend.modules.analytics.constants import APPEAL_MESSAGE_TYPES
from backend.modules.analytics.utils.case_extractor import case_location_key, is_valid_case_title
from backend.modules.analytics.utils.municipality_filter import (
    raw_address_municipality_clause,
    raw_municipality_params,
)

_SLA_HOURS = 48
_SKIP = {"красноярский край", "улица не указана", "не указана", "разное"}

# Маршрутизация категория → ответственный орган (Красноярский край, дефолты).
ROUTING: dict[str, str] = {
    "жкх и городская среда": "Минстрой / УК",
    "дороги и транспорт": "КрУДор / Минтранс",
    "экология и санитарное состояние": "Минэкологии / Росприроднадзор",
    "социальная сфера": "Минсоцполитики / Минздрав / Минобр",
    "управление и обратная связь": "Профильная организация",
    "безопасность и чс": "ГУ МЧС / МВД",
    "экономика, торговля и регулирование": "Роспотребнадзор / Минэконом",
    "связь и цифровая инфраструктура": "Минцифры края / оператор",
    "другое": "—",
}


def classify_status(answered: int, age_hours: int | None, sla_hours: int = _SLA_HOURS) -> str:
    if answered > 0:
        return "in_work"
    if age_hours is None:
        return "new"
    return "overdue" if age_hours > sla_hours else "new"


class IncidentsService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def incidents(self, user: User, *, link_id: uuid.UUID | None = None,
                        municipality_name: str | None = None,
                        limit: int = 1000) -> list[dict]:
        sql = text(f"""
            WITH anchor AS (
                SELECT max(cm.comment_date) AS m
                FROM comments cm
                JOIN publications pub ON pub.id = cm.publication_id
                JOIN public_social_links psl ON psl.id = pub.public_social_link_id
                JOIN publics p ON p.id = psl.public_id
                WHERE p.organization_id = :org AND cm.is_deleted = false
                  AND (CAST(:link AS uuid) IS NULL OR psl.id = CAST(:link AS uuid))
            ),
            cases AS (
                SELECT json_extract_path_text(ca.hierarchy,'case') AS case_name,
                       lower(coalesce(json_extract_path_text(ca.hierarchy,'category'),'')) AS cat,
                       cm.id AS comment_id, cm.comment_date AS d
                FROM comment_analysis ca
                JOIN comments cm ON cm.id = ca.comment_id
                JOIN publications pub ON pub.id = cm.publication_id
                JOIN public_social_links psl ON psl.id = pub.public_social_link_id
                JOIN publics p ON p.id = psl.public_id
                WHERE p.organization_id = :org AND cm.is_deleted = false
                  AND ca.relevance = 'relevant'
                  AND ca.classification_state = 'done'
                  AND ca.message_type = ANY(:appeal_types)
                  AND coalesce(ca.is_official_response, false) = false
                  AND (cm.author_external_id IS NULL OR cm.author_external_id NOT LIKE '-%')
                  AND coalesce(json_extract_path_text(ca.hierarchy,'case'),'') <> ''
                  AND (CAST(:link AS uuid) IS NULL OR psl.id = CAST(:link AS uuid))
                  {raw_address_municipality_clause()}
            ),
            resp AS (
                SELECT r.parent_comment_id AS pid
                FROM comments r
                JOIN comment_analysis ra ON ra.comment_id = r.id
                WHERE ra.is_official_response = true AND r.parent_comment_id IS NOT NULL
                GROUP BY r.parent_comment_id
            )
            SELECT c.case_name, c.cat,
                   count(*) AS mentions,
                   count(resp.pid) AS answered,
                   round(extract(epoch FROM ((SELECT m FROM anchor) - min(c.d))) / 3600.0) AS age_hours
            FROM cases c
            LEFT JOIN resp ON resp.pid = c.comment_id
            GROUP BY c.case_name, c.cat
            ORDER BY mentions DESC
        """)
        rows = (await self._db.execute(sql, {
            "org": user.organization_id, "link": link_id,
            "appeal_types": list(APPEAL_MESSAGE_TYPES),
            **raw_municipality_params(municipality_name),
        })).all()

        # Дедуп адресных кейсов по нормализованной локации (+ категория): «Ачинск» и
        # «город Ачинск» — один инцидент. Ключ — тот же case_location_key, что в PDF.
        merged: dict[tuple, dict] = {}
        for r in rows:
            name = (r.case_name or "").strip()
            if not name or name.lower() in _SKIP or not is_valid_case_title(name):
                continue
            key = (case_location_key(name) or name.lower(), r.cat)
            mentions = int(r.mentions or 0)
            answered = int(r.answered or 0)
            age = 0 if r.age_hours is None else int(r.age_hours)
            m = merged.get(key)
            if m is None:
                merged[key] = {
                    "problem": name, "category": r.cat, "agency": ROUTING.get(r.cat, "—"),
                    "mentions": mentions, "answered": answered, "age_hours": age, "_top": mentions,
                }
            else:
                m["mentions"] += mentions
                m["answered"] += answered
                m["age_hours"] = max(m["age_hours"], age)
                if mentions > m["_top"]:
                    m["problem"], m["_top"] = name, mentions

        out = []
        for m in merged.values():
            m.pop("_top", None)
            m["status"] = classify_status(m["answered"], m["age_hours"] or None)
            out.append(m)
        order = {"overdue": 0, "new": 1, "in_work": 2}
        out.sort(key=lambda x: (-x["mentions"], order.get(x["status"], 3)))
        return out[:limit]
