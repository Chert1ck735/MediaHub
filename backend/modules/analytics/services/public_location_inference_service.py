"""Автоподбор региона и муниципалитета для импортированных площадок."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.public_social_links import PublicSocialLink
from backend.db.publics import Public
from backend.db.regions import Region
from backend.modules.organization.municipalities import (
    KRASNOYARSK_KRAI_NAME,
    infer_krasnoyarsk_municipality,
    mentions_krasnoyarsk_krai,
)
from backend.modules.vk.utils.constants import AUTO_DEFAULT_PUBLIC_DESCRIPTION


class PublicLocationInferenceService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _totals(self, **counters: int) -> dict[str, int]:
        """Итог прогона вместе с общей картиной по площадкам.

        Одного «обновлено: 4» мало: непонятно, это четыре из пяти или из трёхсот.
        """
        base = {
            "considered": 0,
            "updated_publics": 0,
            "updated_region": 0,
            "updated_municipality": 0,
            "unchanged": 0,
        }
        base.update(counters)
        base["total_publics"] = int(
            await self._db.scalar(select(func.count()).select_from(Public)) or 0
        )
        base["with_municipality"] = int(
            await self._db.scalar(
                select(func.count())
                .select_from(Public)
                .where(Public.municipality_name.is_not(None))
            )
            or 0
        )
        return base

    async def infer_missing(self) -> dict[str, int]:
        region = await self._db.scalar(
            select(Region).where(Region.name == KRASNOYARSK_KRAI_NAME)
        )
        if region is None:
            return await self._totals()

        publics = (
            await self._db.execute(
                # Автоматически созданное описание не мешает подбору: территория
                # берётся прежде всего из названия площадки. Прежний фильтр по
                # описанию выбрасывал из проверки большинство импортированных
                # пабликов — до подбора доходило меньше полусотни из трёхсот.
                select(Public)
                .where((Public.region_id.is_(None)) | (Public.municipality_name.is_(None)))
                .order_by(Public.created_at.asc())
            )
        ).scalars().all()

        if not publics:
            return await self._totals()

        titles_by_public: dict[object, list[str]] = {public.id: [] for public in publics}
        link_rows = (
            await self._db.execute(
                select(
                    PublicSocialLink.public_id,
                    PublicSocialLink.title,
                    PublicSocialLink.url,
                ).where(PublicSocialLink.public_id.in_(list(titles_by_public)))
            )
        ).all()
        for row in link_rows:
            titles_by_public.setdefault(row.public_id, []).extend(
                [value for value in (row.title, row.url) if value]
            )

        considered = len(publics)
        updated_publics = 0
        updated_region = 0
        updated_municipality = 0
        unchanged = 0

        for public in publics:
            before = (public.region_id, public.municipality_name)
            # Автоописание одинаково у всех импортированных пабликов и территории
            # не содержит — как источник текста оно бесполезно.
            description = (
                public.description
                if public.description != AUTO_DEFAULT_PUBLIC_DESCRIPTION
                else None
            )
            texts = [public.name, description, *titles_by_public.get(public.id, [])]
            municipality = infer_krasnoyarsk_municipality(*texts)
            has_region_hint = municipality is not None or mentions_krasnoyarsk_krai(*texts)

            if has_region_hint and public.region_id is None:
                public.region_id = region.id
                updated_region += 1

            if (
                municipality
                and public.region_id == region.id
                and not public.municipality_name
            ):
                public.municipality_name = municipality
                updated_municipality += 1

            if (public.region_id, public.municipality_name) != before:
                updated_publics += 1
            else:
                unchanged += 1

        await self._db.commit()
        return await self._totals(
            considered=considered,
            updated_publics=updated_publics,
            updated_region=updated_region,
            updated_municipality=updated_municipality,
            unchanged=unchanged,
        )
