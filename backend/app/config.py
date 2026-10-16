from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    DB_NAME: str
    DB_USER: str
    DB_PASS: str
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432

    ACCESS_TOKEN: str = ""
    VK_API_URL_GET: str = "https://api.vk.com/method/wall.get"
    VK_API_URL_POST: str = "https://api.vk.com/method/wall.post"
    VK_API_VERSION: str = "5.199"
    GROUP_ID: int = 0

    # Пауза между запросами к VK и число постов, опрашиваемых на комментарии
    # одновременно. Дефолты рассчитаны на пользовательский токен; для токена
    # сообщества лимит выше и значения можно увеличить.
    VK_INTER_REQUEST_DELAY: float = 0.34
    VK_COMMENT_FETCH_CONCURRENCY: int = 5
    # Максимум комментариев с одного поста; 0 — без лимита
    VK_COMMENTS_MAX_PER_POST: int = 0

    # Одноклассники. application_key / application_secret_key берутся в старом
    # кабинете OK, OK_ACCESS_TOKEN — через OAuth VK ID. Токен должен
    # принадлежать администратору группы: список тем отдаёт только
    # group.getStatTopics, а это статистика, доступная админам.
    OK_APPLICATION_KEY: str = ""
    OK_APPLICATION_SECRET_KEY: str = ""
    OK_ACCESS_TOKEN: str = ""
    OK_GROUP_ID: str = ""

    OK_INTER_REQUEST_DELAY: float = 0.34
    OK_COMMENT_FETCH_CONCURRENCY: int = 5

    # Telegram читается через пользовательскую MTProto-сессию Telethon:
    # Bot API для этого не подходит и не умеет MTProto-прокси.
    # Сессия — строка StringSession, а не путь к .session, поэтому контейнер
    # не хранит учётные данные на файловой системе.
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""
    TELEGRAM_SESSION_STRING: str = ""
    TELEGRAM_MAX_POSTS: int = 200
    TELEGRAM_COMMENT_FETCH_CONCURRENCY: int = 3

    # WPS — MTProto proxy, поэтому это не HTTP_PROXY/SOCKS_PROXY. По умолчанию
    # прямое соединение запрещено: неполная конфигурация даёт понятную ошибку,
    # а не незаметно обходит прокси.
    TELEGRAM_PROXY_ENABLED: bool = True
    TELEGRAM_PROXY_HOST: str = ""
    TELEGRAM_PROXY_PORT: int = 1443
    TELEGRAM_PROXY_SECRET: str = ""

    # ── Автопарсер комментариев ──────────────────────────────────────────────
    # Фоновый воркер раз в период обходит активные паблики организаций и, если
    # за последнее окно у сети появились неспаршенные комментарии (реальный
    # счётчик > того, что лежит у нас), дотягивает их.
    #
    # AUTOPARSE_ENABLED       — общий рубильник воркера.
    # AUTOPARSE_INTERVAL_HOURS — ДЕФОЛТ периода: ссылка считается «пора проверить»,
    #                            если прошло столько часов с last_autoparse_at
    #                            (24 = раз в сутки). Суперадмин может переопределить
    #                            значение в рантайме (app_settings, см.
    #                            backend/app/runtime_settings.py) — тогда воркер
    #                            и статус читают его из БД, а не отсюда.
    # AUTOPARSE_LOOKBACK_DAYS — окно, за которое ищем дифф и парсим (свежие посты).
    # AUTOPARSE_CHECK_INTERVAL_SECONDS — как часто воркер просыпается искать
    #                            «созревшие» ссылки. Меньше периода, чтобы новые
    #                            ссылки подхватывались без суток ожидания.
    # AUTOPARSE_MAX_POSTS     — потолок постов на ссылку за один проход (защита).
    AUTOPARSE_ENABLED: bool = True
    AUTOPARSE_INTERVAL_HOURS: int = 24
    AUTOPARSE_LOOKBACK_DAYS: int = 7
    AUTOPARSE_CHECK_INTERVAL_SECONDS: int = 3600
    AUTOPARSE_MAX_POSTS: int = 200

    # ── Sentry ──────────────────────────────────────────────────────────────
    # Пустой DSN = трекинг выключен (dev). На проде задать обязательно, иначе
    # падения фоновых воркеров не увидит никто.
    SENTRY_DSN: str = ""
    # Версия сборки — чтобы понимать, в каком релизе появилась ошибка.
    SENTRY_RELEASE: str = ""
    # Трейсинг производительности дорогой; по умолчанию только ошибки.
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    # Structured Logs: слать INFO+ логи в Sentry как просматриваемую ленту (не
    # только ошибки). Удобно смотреть проходы автопарсера/воркеров, но это
    # объём и трафик — можно выключить, оставив только Issues по ошибкам.
    SENTRY_ENABLE_LOGS: bool = True

    # ── Почта: коды подтверждения регистрации ───────────────────────────────
    # Обычный SMTP — подойдёт Яндекс (smtp.yandex.ru:465, SSL), Mail.ru,
    # корпоративный релей. Пароль — «пароль приложения», а не от учётки.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    # От чьего имени письмо. Пусто — берём SMTP_USER.
    SMTP_FROM: str = ""
    SMTP_FROM_NAME: str = "СИГМА"
    # 465 — SSL с первого байта; 587 — STARTTLS. Не путать: на 587 с SSL=true
    # соединение просто зависнет.
    SMTP_USE_SSL: bool = True
    SMTP_USE_TLS: bool = False
    SMTP_TIMEOUT: float = 15.0

    # Сколько живёт код и как часто можно просить новый.
    EMAIL_CODE_TTL_MINUTES: int = 10
    EMAIL_CODE_RESEND_COOLDOWN_SECONDS: int = 60
    EMAIL_CODE_MAX_ATTEMPTS: int = 5

    # Приглашения созданных администратором пользователей. APP_PUBLIC_URL —
    # адрес SPA, который пользователь открывает из письма.
    # Пусто — берём фактический Origin браузера из запроса. На prod можно
    # зафиксировать канонический адрес явно (полезно при нескольких доменах).
    APP_PUBLIC_URL: str = ""
    INVITATION_TTL_HOURS: int = 72
    INVITATION_RESEND_COOLDOWN_SECONDS: int = 60

    # VK parser
    VK_PARSER_GROUP_DOMAIN: str = "svoedelomc"
    VK_PARSER_OUTPUT_FILE: Path = Field(default=Path("posts.csv"))
    VK_PARSER_COUNT_PER_REQUEST: int = 10
    VK_PARSER_MAX_POSTS: int = 10

    # Окружение: 'dev' | 'prod'. На prod включается строгая проверка JWT_SECRET
    # и CORS, traceback в ответ не уходит, tunnel-домены не разрешены.
    APP_ENV: str = "dev"

    # Auth. JWT_SECRET ОБЯЗАТЕЛЬНО задавать в .env — иначе любой, кто видит
    # код, может выпустить токен на любого юзера. Стартап-проверка ниже падает,
    # если переменная не задана или равна дефолтной заглушке.
    JWT_SECRET: str = "DEV_ONLY_SET_JWT_SECRET_IN_ENV"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 7

    # CORS — на prod допустимые origins берутся отсюда (через запятую),
    # tunnel-домены (*.trycloudflare.com / *.ngrok.app) на prod не разрешены.
    CORS_ALLOWED_ORIGINS: str = ""

    # Геокодер адресных кейсов (карта болей): Яндекс → DaData (ФИАС).
    DADATA_TOKEN: str = ""
    DADATA_SECRET: str = ""
    YANDEX_GEOCODER_KEY: str = ""
    GEO_CACHE_PATH: Path = Field(default=Path("data/geo_cache.json"))
    # DaData как запасной геокодер. Выключена: доступен только suggest, а он
    # отвечает почти всегда и часто не тем адресом — неверная точка на карте
    # хуже отсутствующей. Для сравнения провайдеров есть tools/geo_bench.
    GEO_USE_DADATA_FALLBACK: bool = False
    GEO_MAX_NEW_PER_REQUEST: int = 15
    GEO_MISS_TTL_SECONDS: int = 86400
    GEO_TIMEOUT_SECONDS: int = 5
    # Несколько ключей через запятую: когда один выбирает суточную норму,
    # пул переходит на следующий (backend.modules.analytics.utils.geo_keys).
    YANDEX_GEOCODER_KEYS: str = ""
    YANDEX_DAILY_BUDGET: int = 950
    # Кандидаты, которые пока только оцениваем (tools/geo_providers).
    TWOGIS_API_KEY: str = ""
    # Согласие провайдеров: место, найденное одним, верно в трети случаев,
    # подтверждённое вторым — в четырёх пятых. Пока только записываем уровень
    # доверия, отбор по нему включается отдельным флагом.
    GEO_USE_CONSENSUS: bool = False
    GEO_REQUIRE_CONSENSUS: bool = False
    # Регион установки. Если у паблика он не указан, геокодер принимал
    # ответ откуда угодно — так адрес уезжал в Туркестан.
    GEO_DEFAULT_REGION: str = "Красноярский край"

    # LLM provider: openai | ollama
    LLM_PROVIDER: str = "openai"
    OPENAI_COMPATIBLE_BASE_URL: str = "http://192.168.177.172:9012/engines/llama.cpp/v1"
    OPENAI_COMPATIBLE_API_KEY: str = "dummy"
    OPENAI_COMPATIBLE_MODEL: str = "huggingface.co/michaelw9999/qwen3.6-27b-nvfp4-mtp-gguf:NVFP4"
    OPENAI_COMPATIBLE_TIMEOUT: int = 180
    OLLAMA_URL: str = "http://localhost:11434"
    #OLLAMA_MODEL: str = "qwen2.5:7b"
    OLLAMA_MODEL: str = "qwen2.5:3b"
    OLLAMA_TIMEOUT: int = 240
    OLLAMA_NUM_PREDICT_POST: int = 800
    OLLAMA_NUM_PREDICT_ANALYTICS: int = 700
    # Держим модель загруженной в VRAM между вызовами — иначе Ollama выгружает
    # её и тратит десятки секунд на перезагрузку (видно в логах "starting
    # runner"). "30m" / "-1" (вечно) / "0" (выгружать сразу).
    OLLAMA_KEEP_ALIVE: str = "30m"
    # Параллельные LLM-запросы в «Глубокой аналитике». Колено на 8 (bench_concurrency).
    ANALYTICS_LLM_CONCURRENCY: int = 8
    # 3b-префильтр шума перед дорогой 14b. Дёшево отсекает благодарности/спам/
    # флуд — до 14b доходит меньше комментов. На ошибке 3b коммент НЕ теряется
    # (уходит в 14b). Выключить целиком: ANALYTICS_PREFILTER_ENABLED=false.
    ANALYTICS_PREFILTER_ENABLED: bool = True
    ANALYTICS_PREFILTER_MODEL: str = "huggingface.co/qwen/qwen2.5-3b-instruct-gguf:latest"
    ANALYTICS_PREFILTER_MODEL_OLLAMA: str = "qwen2.5:3b"
    ANALYTICS_PREFILTER_CONCURRENCY: int = 16
    # Constrained decoding для классификации комментариев: рантайм ограничивает
    # генерацию JSON Schema, поэтому невалидный JSON и категории вне таксономии
    # становятся невозможны. Если сервер не поддерживает — клиент сам откатится
    # на свободную генерацию; выключить принудительно: LLM_STRUCTURED_OUTPUT=false.
    LLM_STRUCTURED_OUTPUT: bool = True
    # Ниже этого порога уверенности разбор помечается needs_review.
    LLM_LOW_CONFIDENCE_THRESHOLD: float = 0.55
    LLM_USAGE_METRICS_ENABLED: bool = True
    LLM_GPU_METRICS_ENABLED: bool = True
    LLM_GPU_METRICS_INTERVAL: float = 0.5
    LLM_USAGE_METRICS_FILE: Path = Field(default=Path("generated_reports/llm_usage_metrics.jsonl"))
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


    @property
    def DATABASE_URL(self) -> str:
        """Async URL для SQLAlchemy + asyncpg."""
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASS}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Sync URL — пригодится для Alembic / psycopg."""
        return (
            f"postgresql+psycopg://{self.DB_USER}:{self.DB_PASS}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def OWNER_ID(self) -> int:
        """owner_id для VK API — для сообществ это -GROUP_ID."""
        return -self.GROUP_ID

    @property
    def vk_parser_output_abs(self) -> Path:
        """Абсолютный путь к CSV с выгрузкой постов VK."""
        path = self.VK_PARSER_OUTPUT_FILE
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def llm_usage_metrics_file_abs(self) -> Path:
        path = self.LLM_USAGE_METRICS_FILE
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def geo_cache_path_abs(self) -> Path:
        path = self.GEO_CACHE_PATH
        return path if path.is_absolute() else PROJECT_ROOT / path

settings = Settings()


# Стартап-проверка: на проде JWT_SECRET ОБЯЗАН быть длинным значением из .env.
# Без этого любой кто видел код может выпустить токен от имени админа.
_FORBIDDEN_JWT_VALUES = {
    "",
    "DEV_ONLY_SET_JWT_SECRET_IN_ENV",
    "change-me-in-production-secret-key-32chars",
}
if settings.JWT_SECRET in _FORBIDDEN_JWT_VALUES or len(settings.JWT_SECRET) < 32:
    if settings.APP_ENV.lower() == "prod":
        raise RuntimeError(
            "JWT_SECRET не задан или дефолтный. На проде ОБЯЗАТЕЛЬНО задать в .env "
            "(минимум 32 символа). Сгенерировать: python -c "
            "'import secrets; print(secrets.token_urlsafe(48))'"
        )
