"""Лёгкая проверка доступности LLM для индикатора очереди.

Кэш 20с + отдельный пул потоков, чтобы не блокировать event loop и не
конкурировать с фоновым воркером за общий пул asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from backend.app.config import settings

_TTL = 20.0
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-health")
_cache = {"ok": True, "at": 0.0}


def _probe(timeout: float) -> bool:
    provider = (getattr(settings, "LLM_PROVIDER", "openai") or "openai").lower()
    if provider == "ollama":
        base = (getattr(settings, "OLLAMA_URL", "") or "").rstrip("/")
        url = base + "/api/tags" if base else ""
    else:
        base = (getattr(settings, "OPENAI_COMPATIBLE_BASE_URL", "") or "").rstrip("/")
        url = base + "/models" if base else ""
    if not url:
        return True
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True  # сервер ответил (404/401) — значит доступен
    except Exception:  # noqa: BLE001 — сетевой отказ/таймаут = недоступен
        return False


def configured_model_problem(timeout: float = 5.0) -> str | None:
    """Есть ли выбранная в настройках модель на сервере LLM.

    Возвращает текст проблемы или None. Когда в настройках стоит тег, которого
    на сервере нет, рантайм отвечает «model not found» на каждый запрос; когда
    модель не помещается в память видеокарты — падает при загрузке. По логам
    приложения ни то, ни другое не отличить от обычной недоступности.
    """

    provider = (getattr(settings, "LLM_PROVIDER", "openai") or "openai").lower()
    if provider == "ollama":
        return None
    base = (getattr(settings, "OPENAI_COMPATIBLE_BASE_URL", "") or "").rstrip("/")
    wanted = (getattr(settings, "OPENAI_COMPATIBLE_MODEL", "") or "").strip()
    if not base or not wanted:
        return None
    try:
        with urllib.request.urlopen(base + "/models", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — недоступность сервера показывает llm_reachable
        return None
    available = [str(item.get("id") or "") for item in (payload.get("data") or [])]
    if wanted in available:
        return None
    return (
        f"модель «{wanted}» на сервере не найдена; доступны: "
        + (", ".join(available) if available else "список пуст")
    )


async def llm_reachable() -> bool:
    now = time.time()
    if now - _cache["at"] < _TTL:
        return _cache["ok"]
    ok = await asyncio.get_running_loop().run_in_executor(_POOL, _probe, 3.0)
    _cache["ok"], _cache["at"] = ok, now
    return ok
