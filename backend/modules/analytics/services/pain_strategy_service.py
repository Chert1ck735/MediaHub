"""Генерация управленческой стратегии по боли."""
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.rate_limit import RateLimiter
from backend.db import PainStrategy, User
from backend.modules.analytics.repositories.pain_repository import PainRepository
from backend.modules.analytics.repositories.snapshot_repository import SnapshotRepository
from backend.modules.analytics.schemas import StrategyRegenerateResponse
from backend.modules.analytics.services.pain_context_service import PainContextService
from backend.modules.llm.clients import create_llm_client, get_default_llm_model


class PainStrategyRegenerationService:
    """Генерирует и сохраняет новую LLM-стратегию для pain."""

    _rate_limiter = RateLimiter(max_calls=5, window_seconds=60)

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._pain_repository = PainRepository(db)
        self._snapshot_repository = SnapshotRepository(db)
        self._context_service = PainContextService()

    async def regenerate(self, user: User, pain_id: str) -> StrategyRegenerateResponse:
        """Генерирует стратегию, сохраняет PainStrategy и возвращает response."""

        await self._rate_limiter.check_async(
            key=str(user.id),
            route="analytics.regen_strategy",
        )
        pain = await self._pain_repository.get_by_id(pain_id, user)
        if pain is None:
            raise ValueError("Боль не найдена")

        snapshot = await self._snapshot_repository.get_latest_vk(user)
        context = self._context_service.build(snapshot, pain)
        cases = [item["title"] for item in self._context_service.collect_top_cases(
            self._context_service.clean_subproblem_items(snapshot, context)
        )[:5]]
        comment_examples = await self._pain_repository.get_comment_examples(str(pain.id))
        sample_quotes = [
            str(item.get("text") or "").strip().replace("\n", " ")[:240]
            for item in comment_examples[:3]
            if str(item.get("text") or "").strip()
        ]

        description = self._generate_text(
            pain_title=pain.title,
            category=pain.category,
            cases=cases,
            sample_quotes=sample_quotes,
        )
        if not description or len(description) < 30:
            raise RuntimeError("LLM вернул пустой ответ")

        strategy = PainStrategy(
            pain_id=pain.id,
            description=description,
            generated_by_llm=True,
            approved_by_user=False,
        )
        self._db.add(strategy)
        await self._db.commit()
        await self._db.refresh(strategy)
        return StrategyRegenerateResponse(
            pain_id=str(pain.id),
            strategy_id=str(strategy.id),
            description=description,
        )

    @staticmethod
    def _generate_text(
        *,
        pain_title: str,
        category: str | None,
        cases: list[str],
        sample_quotes: list[str],
    ) -> str:
        """Вызывает LLM и возвращает текст стратегии."""

        system_prompt = (
            "Ты — консультант по работе с пабликом. Тебе дают тему обсуждения, "
            "конкретные адресные кейсы и пару цитат. Сформулируй краткий план "
            "для управленца (НЕ текст поста!) — что конкретно сделать офлайн, "
            "чтобы закрыть эту боль. Без воды, без 'необходимо рассмотреть'. "
            "Формат: 3-5 коротких пунктов через перенос строки, начинающихся с '- '. "
            "Каждый пункт — глагол + конкретное действие. Указывай адреса/события, "
            "если они есть в контексте."
        )
        user_prompt = (
            f"Боль: {pain_title}\n"
            f"Категория: {category}\n"
            f"Адресные кейсы: {', '.join(cases) if cases else 'нет'}\n\n"
            f"Цитаты аудитории:\n"
            + ("\n".join(f"- {quote}" for quote in sample_quotes) if sample_quotes else "нет")
        )
        client = create_llm_client(
            model=get_default_llm_model(),
            num_predict=300,
            usage_context="analytics_pain_strategy",
            temperature=0.4,
        )
        try:
            return client.generate([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]).strip()
        finally:
            client.close()
