"""LLM-генерация рекомендаций по контенту для отчёта.

На вход — посчитанная статистика из ``analyzers`` + опциональный
action-plan context (топ-боли, ближайшие события, окно активности).
На выходе — длинный текст рекомендаций, который складывают в раздел
PDF-отчёта «Рекомендации по контенту».

Системный промпт здесь задаёт контекст анализа паблика и его аудитории.
Его формулировки напрямую влияют на тон и структуру PDF.
"""
from __future__ import annotations

import hashlib
import logging
import re

from backend.modules.llm.clients import create_llm_client, get_default_llm_model
from backend.modules.report.utils.numeric import safe_int

logger = logging.getLogger(__name__)

# Рекомендации зависят только от топ-постов; кэшируем по их хэшу, чтобы
# preview/PDF не дёргали LLM повторно (генерация — дорогая, ~десятки секунд).
_RECO_CACHE: dict[str, str] = {}
_RECO_CACHE_MAX = 64

_MD_BULLET = re.compile(r"(?m)^\s*[-*•]\s+")
_MD_HEADING = re.compile(r"(?m)^\s*#{1,6}\s*")


def strip_markdown(text: str) -> str:
    """Убирает markdown-разметку (14b игнорит запрет в промпте и всё равно её ставит)."""
    text = _MD_HEADING.sub("", text)
    text = _MD_BULLET.sub("", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", text)
    return text.strip()


def _reco_cache_key(platform: str, stats: dict) -> str:
    top = stats.get("top_by_likes") or stats.get("top_by_views") or []
    payload = platform + "|" + "|".join(
        f"{safe_int(p.get('views'))}:{(p.get('text') or '')[:80]}" for p in top[:5]
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def cached_recommendations(platform: str, stats: dict, *, pain_context: dict | None = None) -> str:
    """Возвращает рекомендации ТОЛЬКО из кэша (без похода в LLM) — для PDF.

    PDF не должен блокироваться на медленном/недоступном LLM. Если пользователь
    смотрел рекомендации в UI, они уже в кэше; иначе — пустая строка.
    """
    return _RECO_CACHE.get(_reco_cache_key(platform, stats), "")


def format_action_plan_context(pain_context: dict | None) -> str:
    """Превращает action-plan контекст в текстовый блок для LLM-prompt'а.

    Без этого LLM получает только посты и пишет банальные «использовать
    личный опыт». С этим — структурированный input «что болит + что
    запланировано + когда читают», из которого можно собрать конкретный
    план постов.
    """

    if not pain_context:
        return ""
    top_pains = pain_context.get("top_pains") or []
    upcoming = pain_context.get("upcoming_events_by_pain") or {}
    window = pain_context.get("recommended_post_window")
    if not top_pains and not window:
        return ""
    lines = ["", "ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ ДЛЯ ACTION-PLAN:"]
    if window:
        lines.append(f"Лучшее окно публикации (по активности аудитории): {window}.")
    if top_pains:
        lines.append("Топ болей жителей за период:")
        for p in top_pains:
            mentions = p.get("mentions") or 0
            severity = p.get("severity") or ""
            negative = p.get("negative_share") or 0
            base = f"  - {p.get('title')} ({mentions} упоминаний, {severity}, {negative} негативных)"
            events = upcoming.get(p.get("id", ""), [])
            if events:
                ev_strs = []
                for ev in events[:3]:
                    date_short = (ev.get("date") or "")[:10]
                    loc = ev.get("location") or ""
                    loc_suffix = f", {loc}" if loc else ""
                    ev_strs.append(f"{ev.get('title')} ({date_short}{loc_suffix})")
                base += " — связанные события: " + "; ".join(ev_strs)
            else:
                base += " — связанных событий нет"
            lines.append(base)
    lines.append(
        "Используя этот контекст, в раздел 4 «Идеи контента» включи КОНКРЕТНЫЙ план "
        "постов на ближайшие 1-2 недели: для каждой топ-боли — какие посты делать "
        "(анонс события / отчёт / разбор кейса), и под какое окно времени их ставить."
    )
    return "\n".join(lines)


def generate_recommendations(
    platform: str,
    stats: dict,
    *,
    pain_context: dict | None = None,
) -> str:
    """Зовёт LLM с подготовленным промптом и возвращает текст рекомендаций.

    При ошибке LLM возвращает безопасную fallback-строку — caller
    подставит её в PDF, отчёт всё равно соберётся.
    """

    cache_key = _reco_cache_key(platform, stats)
    cached = _RECO_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        key_metrics = [
            f"Площадка: {platform}",
            f"Всего постов: {stats.get('total_posts', 0)}",
            f"Средние просмотры: {stats.get('avg_views', 0)}",
            f"Максимум просмотров: {stats.get('max_views', 0)}",
        ]
        if "avg_likes" in stats:
            key_metrics.append(f"Средние лайки: {stats.get('avg_likes', 0)}")
            key_metrics.append(f"Максимум лайков: {stats.get('max_likes', 0)}")
        if "avg_comments" in stats:
            key_metrics.append(f"Средние комментарии: {stats.get('avg_comments', 0)}")
            key_metrics.append(f"Максимум комментариев: {stats.get('max_comments', 0)}")
        if "group_members" in stats:
            key_metrics.append(f"Подписчиков: {stats.get('group_members', 0)}")
        if "channel" in stats:
            key_metrics.append(f"Канал: {stats.get('channel', '')}")

        top_posts = stats.get("top_by_likes") or stats.get("top_by_views") or []
        top_lines = []
        for i, post in enumerate(top_posts[:5], 1):
            full_text = (post.get("text") or "").replace("\n", " ").strip()
            top_lines.append(
                f"{i}) views={safe_int(post.get('views'))}, likes={safe_int(post.get('likes'))}, "
                f"comments={safe_int(post.get('comments'))} | {full_text}"
            )

        system = (
            "Ты — старший SMM-аналитик, который изучает содержание постов и находит причины их успеха, "
            "учитывай тематику паблика, интересы аудитории и цели "
            "коммуникации. "
            "!!! ЖЁСТКОЕ ПРАВИЛО: В ОТВЕТЕ ЗАПРЕЩЕНА ЛЮБАЯ РАЗМЕТКА !!!\n"
            "Нельзя использовать символы: **, *, _, #, ##. "
            "Нельзя выделять слова жирным, курсивом, заголовками. "
            "Нельзя начинать строки с дефиса или звёздочки для списков. "
            "Только простой текст. Никаких украшений.\n"
            "Твоя задача: внимательно прочитать полные тексты предоставленных топ-5 постов, "
            "выявить в них КОНКРЕТНЫЕ темы, стиль, ключевые слова, заголовки, обращения, "
            "эмоциональную окраску и структурные приёмы, которые привели к высоким метрикам. "
            "В ответе обязательно цитируй фразы из постов и объясняй, почему они сработали.\n"
            "Ответы выдавай на русском языке.\n"
            "Не ссылайся на конкретные посты, только на их содержание, не упоминай номера постов.\n"
            "Пиши КРАТКО — 1-2 предложения на пункт, без воды и повторов. "
            "Формат строго такой (без разметки, только обычный текст):\n"
            "1) Что зашло (3 коротких тезиса с примерами фраз из постов)\n"
            "2) Рекомендации (4 темы/формата, предметно — что повторять)\n"
            "3) Идеи постов (4 идеи: тема + цепляющий заголовок)\n"
            "НЕ давай общих советов вроде 'используйте визуалы и вопросы'. Говори предметно. "
        )

        user_prompt = (
            "Перед тобой пять постов с наибольшим количеством просмотров и лайков. "
            "Твоя задача — проанализировать ИХ ТЕКСТЫ и найти, что именно в содержании привлекло аудиторию. "
            "Не опирайся только на цифры, прочти каждый пост и выяви ключевые темы, стиль, заголовки, "
            "использованные слова и приёмы, которые могли обеспечить высокие метрики. "
            "Дай рекомендации, повторяющие эти успешные находки.\n\n"
            "ДАННЫЕ\n" + "\n".join(key_metrics) + "\n\n"
            "ТОП-ПОСТЫ (полные тексты):\n" + "\n".join(top_lines)
            + format_action_plan_context(pain_context)
        )

        logger.debug(
            "report.recommendations request: model=%s, prompt_chars=%d, metrics=%d, top_posts=%d",
            get_default_llm_model(), len(user_prompt), len(key_metrics), len(top_lines),
        )

        client = create_llm_client(
            model=get_default_llm_model(),
            num_predict=-1,
            usage_context="report_recommendations",
            temperature=0.5,
            top_p=0.9,
            top_k=40,
            repeat_penalty=1.08,
        )
        result = client.generate(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ]
        ).strip()

        logger.debug("report.recommendations response: %d chars", len(result))
        result = strip_markdown(result)
        if len(_RECO_CACHE) >= _RECO_CACHE_MAX:
            _RECO_CACHE.clear()
        _RECO_CACHE[cache_key] = result
        return result
    except Exception as e:
        logger.exception("report.recommendations failed: %s", e)
        return (
            "Не удалось сгенерировать рекомендации. "
            "Проверьте, что LLM-сервис доступен, и попробуйте позже."
        )
