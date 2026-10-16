# Разработка и запуск

## Требования

- Python 3.11 — версия, используемая Docker-образом backend и GitHub Actions.
- Node.js 22 и npm — для интерфейса.
- PostgreSQL 16 — версия локального Compose и CI.
- Отдельный сервер LLM — для генерации и классификации; ключи внешних сервисов — для соответствующих интеграций.

## Локальный запуск без контейнеров

Из корня проекта в Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
cp frontend/.env.example frontend/.env
```

В `.env` задайте параметры уже запущенного PostgreSQL (`DB_HOST=localhost`), имя существующей пустой базы, логин, пароль и случайный `JWT_SECRET` от 32 символов. Для создания базы можно использовать `createdb -h localhost -U postgres media_project` или любой клиент PostgreSQL.

```bash
python -m alembic upgrade head
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

В другом терминале:

```bash
cd frontend
npm ci
npm run dev
```

Интерфейс доступен на <http://localhost:5173>, Swagger — на <http://localhost:8000/docs>. Vite проксирует запросы `/api` на `http://127.0.0.1:8000`. Другой адрес можно задать через переменную процесса `VITE_BACKEND_TARGET`.

В Windows виртуальное окружение активируется командой `.venv\Scripts\activate`. После настройки `.env`, установки зависимостей и применения миграций можно использовать `start-dev.bat`.

Первый пользователь регистрируется через интерфейс и получает собственную организацию с ролью администратора. В режиме `dev` без SMTP код подтверждения доступен в логах backend. В `prod` для отправки кодов требуется SMTP.

## LLM

Приложение обращается к внешнему серверу модели. Модели, веса и GPU-инфраструктура в репозиторий не входят.

Для OpenAI-совместимого сервера:

```dotenv
LLM_PROVIDER=openai
OPENAI_COMPATIBLE_BASE_URL=http://localhost:8080/v1
OPENAI_COMPATIBLE_API_KEY=dummy
OPENAI_COMPATIBLE_MODEL=your-model-id
```

Укажите фактический URL API и идентификатор загруженной модели. Если сервер требует ключ, замените `dummy` действительным значением. При включённом `ANALYTICS_PREFILTER_ENABLED` используется отдельная модель предварительной фильтрации: задайте `ANALYTICS_PREFILTER_MODEL` либо отключите фильтр через `ANALYTICS_PREFILTER_ENABLED=false`.

Для Ollama:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
ANALYTICS_PREFILTER_ENABLED=false
```

Модель нужно предварительно установить на сервере Ollama. Это пример конфигурации, а не гарантия качества классификации конкретной моделью.

В Docker оба URL должны быть доступны из контейнера backend. Для модели на хосте используйте его доступный IP либо настроенный адрес `host.docker.internal`; в Linux этот псевдоним может потребовать явной настройки Docker. Сервер модели должен принимать соединения из соответствующей сети.

## Интеграции

| Интеграция | Настройки backend | Условия |
| --- | --- | --- |
| ВКонтакте | `ACCESS_TOKEN`, при необходимости `GROUP_ID` | Токен с правами для нужных методов API |
| Одноклассники | `OK_APPLICATION_KEY`, `OK_APPLICATION_SECRET_KEY`, `OK_ACCESS_TOKEN`, `OK_GROUP_ID` | Права приложения и администратора группы |
| Telegram | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING`, `TELEGRAM_PROXY_*` | [Инструкция MTProto](telegram.md) |
| Геокодирование | `YANDEX_GEOCODER_KEY` или `YANDEX_GEOCODER_KEYS`; при настройке резервного провайдера — `DADATA_*` | Действующие ключи и лимиты провайдера |
| Карта в браузере | `VITE_YANDEX_MAPS_KEY` в `frontend/.env` | Публичный ключ JavaScript API с ограничениями по доменам |
| Почта | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_SSL`, `SMTP_USE_TLS` | Учётная запись SMTP |
| Ошибки | `SENTRY_DSN`, `SENTRY_RELEASE` | Пустой DSN отключает отправку событий |

Полный набор доступных параметров и значения по умолчанию — в `backend/app/config.py`. `.env.example` содержит основные настройки для старта.

## Тесты

Установите `requirements-dev.txt`. Команды выполняются из корня с активным виртуальным окружением и заполненным `.env`.

Для тестов используйте отдельную базу, например `media_project_test`. `DB_NAME` также должен указывать на тестовую базу: часть тестов использует настройки приложения, а часть — `TEST_DATABASE_URL`.

```bash
createdb -h localhost -U postgres media_project_test
export DB_NAME=media_project_test
export TEST_DATABASE_URL='postgresql+asyncpg://postgres:your_test_password@localhost:5432/media_project_test'
python -m alembic upgrade head
python -m pytest -v --tb=short
```

Пароль в URL должен соответствовать `DB_PASS`; специальные символы в URL нужно кодировать. Тестовые фикстуры очищают таблицы. Никогда не направляйте тесты на рабочую базу. При недоступной тестовой БД часть тестов пропускается: наличие `skipped` не подтверждает прохождение интеграционных проверок.

Сервис `tests` в Compose включается только профилем `test` и собирается с dev-зависимостями. Перед его запуском отдельно настройте тестовую БД и окружение: по умолчанию Compose использует параметры `.env.docker`.

Браузерные тесты:

```bash
cd frontend
npm ci
npx playwright install chromium
npm run test:e2e
```

Playwright запускает Vite автоматически; текущие сценарии подменяют ответы API тестовыми данными.

Проверка типов и сборка интерфейса:

```bash
cd frontend
npm run build
```

## Развёртывание

Локальный Compose запускает Vite dev server и backend с `--reload`. Для публичной установки подготовьте отдельную конфигурацию развёртывания.

1. Соберите frontend через `npm ci && npm run build` из `frontend/`.
2. Установите `APP_ENV=prod`, случайный `JWT_SECRET`, `CORS_ALLOWED_ORIGINS` и SMTP; при необходимости задайте `APP_PUBLIC_URL` и Sentry.
3. Выполните резервное копирование существующей БД и `python -m alembic upgrade head`.
4. Запустите backend без `--reload`. Если `frontend/dist` находится рядом с исходниками, FastAPI автоматически раздаёт сборку. Альтернативный путь задаётся через `FRONTEND_DIST`.
5. Настройте HTTPS и reverse proxy. При отдельной раздаче SPA проксируйте `/api` в backend и предусмотрите возврат `index.html` для клиентских маршрутов. Для отдельного домена API задайте `VITE_API_BASE_URL` до сборки.
6. Проверьте `/health/live` и `/health/ready`, регистрацию, доступ к модели и выбранным социальным сетям.

`docker-compose-prod.yml` и `.gitlab-ci.yml` сохранены как конфигурация исходного серверного окружения: они используют частный registry, собственные runner tags, внешнюю Docker-сеть и переменные CI/CD. Они не являются универсальным production-шаблоном. Переменные `VITE_*` читаются при сборке Vite; для dev server — при его запуске.

Dockerfile backend и frontend по умолчанию используют публичные базовые образы. При необходимости задайте `PYTHON_IMAGE`, `NODE_IMAGE` и `PIP_INDEX_URL` как build arguments. Учётные данные частного реестра не следует записывать в Dockerfile.

Для резервного копирования предусмотрен `tools/backup_db.py`; локальные бэкапы исключены из Git. Старый `media-project.sql` не используется для установки: актуальный способ подготовки схемы — миграции Alembic.
