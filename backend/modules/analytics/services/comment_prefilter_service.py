"""3b-префильтр шума перед дорогой 14b-классификацией.

Дешёвый бинарный гейт на малой модели: «мусор» (благодарность/спам/флуд)
отсекаем, «обращение» (любая проблема/просьба/предмет) пропускаем дальше в 14b.
Детектор настроен НА ШУМ (лёгкое направление для 3b); при ошибке или сомнении
коммент НЕ теряется, а уходит в 14b — recall важнее экономии. Промпт проверен в
``tools/prefilter_probe_3b``.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable, Optional

from backend.app.config import settings
from backend.modules.llm.providers.client_factory import create_llm_client

SYSTEM = (
    "Ты сортируешь комментарии в паблике на два класса.\n"
    "МУСОР — чистая благодарность/похвала без проблемы, поздравление, реклама/спам, "
    "флуд и смайлы, оффтоп не про город.\n"
    "ОБРАЩЕНИЕ — есть любая проблема, нехватка, претензия, просьба, упомянут объект/услуга/место; "
    "даже если коротко, косвенно или с иронией.\n"
    "Примеры МУСОР: «Спасибо, молодцы!»; «С праздником вас!»; «👍👍👍»; «Куплю авто дорого, пишите».\n"
    "Примеры ОБРАЩЕНИЕ: «Спасибо за ответ, но школы так и нет»; «ТЭЦ газифицировать бы»; "
    "«Опять яму объезжаю»; «Мусор две недели не вывозят».\n"
    "Ответь ОДНИМ словом: МУСОР или ОБРАЩЕНИЕ."
)

ProgressFn = Callable[[int, int], Awaitable[None]]


def _prefilter_model() -> str:
    provider = (settings.LLM_PROVIDER or "").strip().lower()
    if provider == "ollama":
        return settings.ANALYTICS_PREFILTER_MODEL_OLLAMA
    return settings.ANALYTICS_PREFILTER_MODEL


async def prefilter_keep_ids(
    items: list[tuple[uuid.UUID, str]],
    *,
    on_progress: Optional[ProgressFn] = None,
) -> set[uuid.UUID]:
    """Возвращает id комментов, которые надо отправить в 14b (шум отсеян).

    Префильтр выключен или список пуст → возвращаем всё без вызовов LLM.
    """
    if not items:
        return set()
    if not settings.ANALYTICS_PREFILTER_ENABLED:
        return {cid for cid, _ in items}

    client = create_llm_client(
        model=_prefilter_model(),
        num_predict=5,  # «МУСОР»/«ОБРАЩЕНИЕ» — короче обрежется и сломает разбор
        temperature=0.0,
        usage_context="analytics_prefilter",
    )
    sem = asyncio.Semaphore(max(1, int(settings.ANALYTICS_PREFILTER_CONCURRENCY)))

    async def _one(cid: uuid.UUID, text: str) -> tuple[uuid.UUID, bool]:
        async with sem:
            try:
                ans = await asyncio.to_thread(
                    client.generate,
                    [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": text[:1500]},
                    ],
                )
            except Exception:  # noqa: BLE001 — сбой 3b не должен терять боль
                return cid, True
            return cid, not ans.strip().lower().startswith("мус")

    keep: set[uuid.UUID] = set()
    tasks = [asyncio.create_task(_one(cid, t)) for cid, t in items]
    done = 0
    for fut in asyncio.as_completed(tasks):
        cid, is_keep = await fut
        if is_keep:
            keep.add(cid)
        done += 1
        if on_progress and (done % 20 == 0 or done == len(items)):
            await on_progress(done, len(items))
    return keep
