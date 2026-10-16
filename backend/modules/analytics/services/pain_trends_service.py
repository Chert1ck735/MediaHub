"""Тренды по упоминаниям болей с гранулярностью под выбранный период."""
import math
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User
from backend.modules.analytics.repositories.pain_repository import PainRepository
from backend.modules.analytics.schemas import PainTrendItem
from backend.modules.analytics.utils.public_link_filter import PublicSocialLinkFilter


# Спарклайн на карточке узкий: больше точек превращают его в шум.
_MAX_BUCKETS = 26
# Лестница гранулярности: день → неделя → месяц. Берём самое мелкое деление,
# при котором точек ещё не слишком много: неделя → дни, 3 месяца → недели.
_BUCKET_LADDER = (1, 7, 30)


def _pick_bucket_days(span_days: int) -> int:
    """Размер бакета в днях под длину периода."""

    for bucket in _BUCKET_LADDER:
        if math.ceil(span_days / bucket) <= _MAX_BUCKETS:
            return bucket
    return max(1, math.ceil(span_days / _MAX_BUCKETS))


class PainTrendsService:
    """Считает sparkline-тренды pain'ов без SQL в router."""

    def __init__(self, db: AsyncSession, *, pain_repository: PainRepository | None = None) -> None:
        self._db = db
        self._pain_repository = pain_repository or PainRepository(db)

    async def list_trends(
        self,
        user: User,
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> list[PainTrendItem]:
        """Ряд упоминаний по бакетам, размер которых подобран под период.

        Сумма ряда = упоминания карточки за тот же период (тот же дедуп и фильтры).
        """

        # Данные историчные — окно якорим к последней дате данных, а не к «сегодня»,
        # иначе на исторических комментариях тренд пустой/обрезанный.
        kwargs = {"since": None, "link_id": link_id}
        if municipality_name is not None:
            kwargs["municipality_name"] = municipality_name
        rows = await self._pain_repository.list_pain_comment_mentions(user, **kwargs)
        dated: list[tuple[str, datetime]] = []
        for pain_id, _comment_id, created in rows:
            if created is None or pain_id is None:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            dated.append((str(pain_id), created))
        if not dated:
            return []

        end = max(c for _, c in dated).replace(hour=0, minute=0, second=0, microsecond=0)
        if since is None:
            span_days = (end - min(c for _, c in dated)).days
        else:
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            span_days = (datetime.now(timezone.utc) - since).days
        span_days = max(1, span_days)
        bucket_days = _pick_bucket_days(span_days)
        buckets = max(1, min(math.ceil(span_days / bucket_days), _MAX_BUCKETS))

        # Границы якорим к КОНЦУ последнего дня с данными, а не к его началу.
        # Иначе последний бакет вмещал бы только этот день против полных
        # bucket_days у остальных — и график systematically «падал» на хвосте.
        end_exclusive = end + timedelta(days=1)
        start = end_exclusive - timedelta(days=buckets * bucket_days)

        counts: dict[str, list[int]] = {}
        for pain_id, created in dated:
            index = (created - start).days // bucket_days
            if 0 <= index < buckets:
                counts.setdefault(pain_id, [0] * buckets)[index] += 1
        return [
            PainTrendItem(pain_id=pain_id, counts=values, bucket_days=bucket_days)
            for pain_id, values in counts.items()
        ]
