# Telegram-импорт

Импортируются публичные каналы `t.me/<канал>` и отдельные публикации. Если у канала подключена discussion-группа, также сохраняются текстовые комментарии и ответы на них. Закрытые каналы, инвайт-ссылки и обычные чаты не импортируются.

## Подключение

Интеграция использует пользовательскую MTProto-сессию Telethon, а не Bot API. Понадобятся `api_id` и `api_hash` приложения с <https://my.telegram.org>, Telegram-аккаунт и авторизованная строка `StringSession`.

В `.env` для локального backend или `.env.docker` для Docker задайте:

```dotenv
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PROXY_ENABLED=true
TELEGRAM_PROXY_HOST=your-mtproto-proxy-host
TELEGRAM_PROXY_PORT=1443
TELEGRAM_PROXY_SECRET=your_mtproto_proxy_secret
TELEGRAM_SESSION_STRING=your_authorized_session_string
```

## Прокси

По умолчанию прямое соединение запрещено: backend требует настроенный MTProto-прокси. HTTP- и SOCKS-прокси в этом режиме не подходят.

В текущей поставке нет исходников WPS или сервиса `telegram-proxy` в Compose. Используйте отдельно развёрнутый совместимый MTProto-прокси и укажите адрес, доступный из backend. Если прямое соединение разрешено в вашей среде, его можно явно включить через `TELEGRAM_PROXY_ENABLED=false`.

## Создание сессии

Установите Python-зависимости и на доверенной машине задайте переменные `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PROXY_HOST`, `TELEGRAM_PROXY_PORT` и `TELEGRAM_PROXY_SECRET` в окружении процесса. Скрипт не загружает `.env` автоматически и всегда использует прокси, даже если у backend отключено его использование.

```bash
python tools/create_telegram_session.py
```

Скрипт запросит номер телефона, код Telegram и, при включённой двухэтапной аутентификации, пароль. Затем выведет `TELEGRAM_SESSION_STRING`. Сохраните значение в локальном env-файле и перезапустите backend.

Строка сессии предоставляет доступ к аккаунту. Не добавляйте её в Git, тикеты, скриншоты или журналы. Локальные `.env*` и файлы `*.session` исключены из Git и Docker build context.
