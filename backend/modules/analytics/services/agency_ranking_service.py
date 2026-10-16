"""Рейтинг организаций по реакции на обращения — агрегат поверх реестра инцидентов."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.users import User
from backend.modules.analytics.services.incidents_service import IncidentsService


def aggregate_by_agency(incidents: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for inc in incidents:
        agency = inc["agency"]
        if agency == "—":
            continue
        a = agg.setdefault(agency, {
            "agency": agency, "incidents": 0, "mentions": 0,
            "answered": 0, "overdue": 0, "new": 0,
        })
        a["incidents"] += 1
        a["mentions"] += inc["mentions"]
        if inc["status"] == "in_work":
            a["answered"] += 1
        elif inc["status"] == "overdue":
            a["overdue"] += 1
        else:
            a["new"] += 1

    out = []
    for a in agg.values():
        decided = a["answered"] + a["overdue"]  # new (в срок, ещё не просрочены) не штрафуем
        a["response_rate"] = round(a["answered"] / decided * 100, 1) if decided else 0.0
        out.append(a)
    out.sort(key=lambda x: (x["response_rate"], -x["overdue"]))
    return out


class AgencyRankingService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def rank(
        self,
        user: User,
        *,
        link_id: uuid.UUID | None = None,
        municipality_name: str | None = None,
    ) -> list[dict]:
        incidents = await IncidentsService(self._db).incidents(
            user,
            link_id=link_id,
            municipality_name=municipality_name,
            limit=1000,
        )
        return aggregate_by_agency(incidents)
