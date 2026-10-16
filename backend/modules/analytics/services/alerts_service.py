"""Алерты: всплески обращений по категориям (последнее окно vs предыдущее).

Окна привязаны к ПОСЛЕДНЕЙ дате в данных организации (comment_date), а не к
«сейчас» — данные историчные, от wall-clock окна были бы пустыми.
"""
from __future__ import annotations


from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.users import User
from backend.modules.analytics.constants import APPEAL_MESSAGE_TYPES
from backend.modules.analytics.utils.public_link_filter import (
    PublicSocialLinkFilter,
    normalize_public_social_link_ids,
)
from backend.modules.analytics.utils.municipality_filter import (
    raw_comment_municipality_clause,
    raw_municipality_params,
)

_MIN_RECENT = 5        # меньше — статистический шум, не алерт
_GROWTH = 1.5          # recent ≥ prior × 1.5 → всплеск
_MIN_PRIOR = 3         # база меньше — процент роста недостоверен (1 → 27 это «+2600%»)


def is_spike(recent: int, prior: int, min_recent: int = _MIN_RECENT, growth: float = _GROWTH) -> bool:
    if recent < min_recent or recent <= prior:
        return False
    return recent >= prior * growth


class AlertsService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def alerts(self, user: User, *, window_days: int = 7,
                     link_id: PublicSocialLinkFilter = None,
                     municipality_name: str | None = None) -> list[dict]:
        link_ids = normalize_public_social_link_ids(link_id)
        anchor_link_clause = "AND psl.id IN :anchor_link_ids" if link_ids else ""
        scope_link_clause = "AND psl.id IN :scope_link_ids" if link_ids else ""
        sql = text(f"""
            WITH anchor AS (
                SELECT max(cm.comment_date) AS m,
                       min(cm.comment_date) AS first_seen
                FROM comments cm
                LEFT JOIN comment_analysis ca ON ca.comment_id = cm.id
                JOIN publications pub ON pub.id = cm.publication_id
                JOIN public_social_links psl ON psl.id = pub.public_social_link_id
                JOIN publics p ON p.id = psl.public_id
                WHERE p.organization_id = :org AND cm.is_deleted = false
                  AND cm.comment_date IS NOT NULL
                  {anchor_link_clause}
                  {raw_comment_municipality_clause()}
            ),
            scope AS (
                SELECT cm.comment_date AS d,
                       json_extract_path_text(ca.hierarchy,'category') AS cat
                FROM comment_analysis ca
                JOIN comments cm ON cm.id = ca.comment_id
                JOIN publications pub ON pub.id = cm.publication_id
                JOIN public_social_links psl ON psl.id = pub.public_social_link_id
                JOIN publics p ON p.id = psl.public_id
                WHERE p.organization_id = :org AND cm.is_deleted = false
                  AND ca.relevance = 'relevant' AND cm.comment_date IS NOT NULL
                  AND ca.classification_state = 'done'
                  AND ca.message_type = ANY(:appeal_types)
                  AND coalesce(ca.is_official_response, false) = false
                  AND (cm.author_external_id IS NULL OR cm.author_external_id NOT LIKE '-%')
                  AND coalesce(json_extract_path_text(ca.hierarchy,'category'),'') <> ''
                  {scope_link_clause}
                  {raw_comment_municipality_clause()}
            )
            SELECT cat,
                   count(*) FILTER (WHERE d >= (SELECT m FROM anchor) - make_interval(days => :w)) AS recent,
                   count(*) FILTER (WHERE d >= (SELECT m FROM anchor) - make_interval(days => :w2)
                                    AND d <  (SELECT m FROM anchor) - make_interval(days => :w)) AS prior,
                   -- Покрыто ли прошлое окно данными: у только что импортированного
                   -- паблика история начинается внутри него, и сравнивать не с чем.
                   (SELECT first_seen <= m - make_interval(days => :w2) FROM anchor) AS covered
            FROM scope GROUP BY cat
        """)
        params = {
            "org": user.organization_id,
            "w": window_days, "w2": window_days * 2,
            "appeal_types": list(APPEAL_MESSAGE_TYPES),
            **raw_municipality_params(municipality_name),
        }
        if link_ids:
            sql = sql.bindparams(
                bindparam("anchor_link_ids", expanding=True),
                bindparam("scope_link_ids", expanding=True),
            )
            params["anchor_link_ids"] = link_ids
            params["scope_link_ids"] = link_ids
        rows = (await self._db.execute(sql, params)).all()

        alerts = []
        for r in rows:
            # Прошлое окно не покрыто историей — всплеск недоказуем ни по одной
            # категории, поэтому не показываем ничего, а не «рост с нуля».
            if not r.covered:
                return []
            recent, prior = int(r.recent or 0), int(r.prior or 0)
            if not is_spike(recent, prior):
                continue
            alerts.append({
                "category": r.cat,
                "recent": recent,
                "prior": prior,
                # База меньше _MIN_PRIOR — процент был бы шумом, показываем алерт
                # без числа (фронт трактует None как «рост с нуля»).
                "growth_pct": (
                    round((recent - prior) / prior * 100) if prior >= _MIN_PRIOR else None
                ),
                "window_days": window_days,
            })
        alerts.sort(key=lambda a: (a["growth_pct"] is None, a["growth_pct"] or 0, a["recent"]), reverse=True)
        return alerts
