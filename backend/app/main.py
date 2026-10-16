from contextlib import asynccontextmanager
import logging
import os
import traceback
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from backend.app.config import settings
from backend.db.database import engine, AsyncSession, get_db
from backend.app.slow_requests import log_slow_requests, snapshot, watch_event_loop_lag
from backend.db.schema_sync import ensure_runtime_schema
from backend.modules.vk import router as vk_router
from backend.modules.ok import router as ok_router
from backend.modules.telegram.router import router as telegram_router
from backend.modules.llm import router as llm_router
from backend.modules.condition import router as condition_router
from backend.modules.report import router as report_router
from backend.modules.auth import router as auth_router
from backend.modules.posts import router as posts_router
from backend.modules.calendar import router as calendar_router
from backend.modules.publications.router import router as publications_router
from backend.modules.events import router as events_router
from backend.modules.analytics import router as analytics_router
from backend.modules.patterns.router import router as patterns_router
from backend.modules.jobs.router import router as jobs_router
from backend.modules.organization.router import router as organization_router
from backend.modules.autoparse.router import router as autoparse_router

import sentry_sdk

from backend.app.sentry import init_sentry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
DEBUG_TRACEBACK = os.getenv("BACKEND_DEBUG", "false").lower() in {"1", "true", "yes"}

# Инициализация вынесена в backend/app/sentry.py: там LoggingIntegration
# (logger.exception -> событие), фильтр шума 4xx и вычистка секретов.
init_sentry()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_runtime_schema(engine)
    logger.info("Ensured runtime schema compatibility")

    # Фоновый воркер: берёт pending-записи и классифицирует через LLM (done/failed).
    import asyncio
    from backend.db.database import async_session_maker
    from backend.modules.analytics.classification import process_pending_loop

    classifier_stop = asyncio.Event()
    classifier_task = asyncio.create_task(
        process_pending_loop(
            db_factory=async_session_maker,
            batch_size=50,
            idle_sleep_s=10.0,
            concurrency=4,
            stop_event=classifier_stop,
        ),
        name="classification-worker",
    )
    logger.info("Started classification worker")

    # Фоновый автопарсер: раз в период тянет новые комменты прикреплённых
    # пабликов, если у сети их больше, чем спаршено у нас.
    from backend.modules.autoparse.worker import autoparse_loop

    autoparse_stop = asyncio.Event()
    autoparse_task = asyncio.create_task(
        autoparse_loop(async_session_maker, stop_event=autoparse_stop),
        name="autoparse-worker",
    )
    logger.info("Started autoparse worker")

    async def _stop_worker(name: str, stop: asyncio.Event, task: asyncio.Task) -> None:
        stop.set()
        try:
            # Даём воркеру шанс корректно завершить текущую итерацию.
            await asyncio.wait_for(task, timeout=15.0)
        except asyncio.TimeoutError:
            logger.warning("%s shutdown timed out, cancelling", name)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    loop_watch_stop = asyncio.Event()
    loop_watch_task = asyncio.create_task(
        watch_event_loop_lag(loop_watch_stop), name="loop-lag-watch"
    )

    # Модель на сервере могли переименовать или не загрузить. Тогда каждый
    # запрос к LLM отвечает «model not found» либо падает по памяти GPU, а в
    # логе приложения это неотличимо от обычной ошибки запроса.
    from backend.modules.analytics.llm_health import configured_model_problem

    async def _check_llm_model() -> None:
        problem = await asyncio.get_running_loop().run_in_executor(
            None, configured_model_problem
        )
        if problem:
            logger.error("LLM: %s", problem)

    llm_model_task = asyncio.create_task(_check_llm_model(), name="llm-model-check")

    try:
        yield
    finally:
        llm_model_task.cancel()
        await _stop_worker("Loop lag watch", loop_watch_stop, loop_watch_task)
        await _stop_worker("Autoparse worker", autoparse_stop, autoparse_task)
        await _stop_worker("Classification worker", classifier_stop, classifier_task)
        await engine.dispose()


app = FastAPI(
    title="Bezumny MAX",
    description="Platforma dlya analitiki",
    version="1.0.0",
    lifespan=lifespan,
)


# Лимит размера тела запроса (Content-Length). Реальные API нашего бэка
# работают с короткими JSON'ами (~5-50 KB максимум — generate-post, импорт
# events). Гигантский body — это либо ошибка клиента, либо попытка OOM:
# uvicorn без лимита будет читать запрос в память пока не закончится RAM.
# 2 МБ — комфортный потолок (CSV в /api/events/import — отдельный лимит
# на upload через UploadFile, тут не пересекается).
_MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 МБ


@app.middleware("http")
async def _log_slow_requests(request: Request, call_next):
    return await log_slow_requests(request, call_next)


@app.middleware("http")
async def _enforce_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > _MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large (>{_MAX_BODY_BYTES} bytes)"},
                )
        except ValueError:
            pass  # некорректный Content-Length — пропустим, fastapi сам отвалит
    return await call_next(request)

# CORS:
# - dev: localhost + LAN + tunnel-домены (cloudflared / ngrok) — для теста.
# - prod: только явный список из settings.CORS_ALLOWED_ORIGINS (через запятую).
#   На prod tunnel-домены НЕ разрешены: allow_credentials=True + дикий regex
#   даёт CSRF-вектор на любой *.trycloudflare.com.
_IS_PROD = settings.APP_ENV.lower() == "prod"

if _IS_PROD:
    _prod_origins = [
        o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()
    ]
    if not _prod_origins:
        raise RuntimeError(
            "APP_ENV=prod, но CORS_ALLOWED_ORIGINS пуст. "
            "Укажи список origin'ов через запятую в .env, например: "
            "CORS_ALLOWED_ORIGINS=https://media.example.ru,https://admin.example.ru"
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_prod_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
else:
    CORS_ALLOW_REGEX = (
        r"^https?://("
        r"localhost(:\d+)?"
        r"|127\.0\.0\.1(:\d+)?"
        r"|192\.168\.\d{1,3}\.\d{1,3}(:\d+)?"
        r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?"
        r"|172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3}(:\d+)?"
        r"|[A-Za-z0-9-]+\.trycloudflare\.com"
        r"|[A-Za-z0-9-]+\.ngrok(-free)?\.(app|io)"
        r")$"
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=CORS_ALLOW_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    sentry_sdk.capture_exception(exc)
    tb = traceback.format_exc()
    logger.error("Unhandled exception on %s %s:\n%s", request.method, request.url, tb)
    # На prod не отдаём наружу исходный текст ошибки — там часто просвечивают
    # имена таблиц/полей/файлов. В dev и при BACKEND_DEBUG=1 — отдаём полностью.
    if DEBUG_TRACEBACK or not _IS_PROD:
        payload = {"detail": str(exc)}
        if DEBUG_TRACEBACK:
            payload["traceback"] = tb
    else:
        payload = {"detail": "Internal server error"}
    return JSONResponse(status_code=500, content=payload)


app.include_router(auth_router)
app.include_router(posts_router)
app.include_router(publications_router)
app.include_router(calendar_router)
app.include_router(events_router)
app.include_router(vk_router)
app.include_router(ok_router)
app.include_router(telegram_router)
app.include_router(llm_router)
app.include_router(condition_router)
app.include_router(report_router)
app.include_router(analytics_router)
app.include_router(patterns_router)
app.include_router(jobs_router)
app.include_router(organization_router)
app.include_router(autoparse_router)


@app.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    return {"status": "ok", "db_response": result.scalar()}


@app.get("/health/slow", include_in_schema=False)
async def health_slow():
    """Последние медленные ответы и текущая задержка event loop.

    Различает две причины таймаутов: тяжёлый запрос к базе или занятый
    фоновой работой цикл событий. Доступа к логам сервера нет, поэтому
    снимок отдаётся в браузер.
    """
    return snapshot()


@app.get("/health/live", include_in_schema=False)
async def health_live():
    """Liveness probe для оркестраторов (docker/k8s/nginx upstream).

    Не ходит в БД — отвечает что процесс жив. Используется чтобы НЕ
    рестартовать pod если БД временно недоступна (DB-проблема — не
    причина перезапускать бэк).
    """
    return {"status": "alive"}


@app.get("/health/ready", include_in_schema=False)
async def health_ready(db: AsyncSession = Depends(get_db)):
    """Readiness probe: бэк готов принимать трафик.

    Проверяет что критичные зависимости отвечают:
     - БД доступна для SELECT (asyncpg pool здоров);
     - alembic_version присутствует (миграции хотя бы раз накатывались).

    На k8s/docker нужно использовать ИМЕННО ЭТУ ручку для traffic gating,
    а /health/live — для restart-policy.
    """
    try:
        check = await db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        rev = check.scalar()
        if not rev:
            return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "no alembic_version"})
        return {"status": "ready", "alembic_revision": rev}
    except Exception as e:
        logger.warning("health/ready failed: %s", e)
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "db_unavailable"})


# ---------- Раздача собранного фронта (опционально, prod-режим) ----------
def _resolve_frontend_dist() -> Optional[Path]:
    env_dir = os.getenv("FRONTEND_DIST")
    if env_dir:
        candidate = Path(env_dir).expanduser().resolve()
        return candidate if candidate.is_dir() else None
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "frontend" / "dist",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


_FRONTEND_DIST = _resolve_frontend_dist()

if _FRONTEND_DIST is not None:
    logger.info("Serving frontend from %s", _FRONTEND_DIST)
    _assets_dir = _FRONTEND_DIST / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def root_index():
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        target = (_FRONTEND_DIST / full_path).resolve()
        if _FRONTEND_DIST in target.parents and target.is_file():
            return FileResponse(target)
        return FileResponse(_FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    async def root():
        return {"message": "Backend is running"}


if __name__ == "__main__":
    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "8000"))
    reload_flag = os.getenv("BACKEND_RELOAD", "true").lower() in {"1", "true", "yes"}
    reload_dirs = ["backend", "alembic"] if reload_flag else None
    uvicorn.run("backend.app.main:app", host=host, port=port, reload=reload_flag, reload_dirs=reload_dirs)
