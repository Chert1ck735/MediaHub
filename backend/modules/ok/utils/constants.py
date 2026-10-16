"""Константы OK-модуля."""

API_BASE = "https://api.ok.ru/fb.do"

MAX_RETRIES = 4
RETRY_DELAY_SEC = 1.5
INTER_REQUEST_DELAY_SEC = 0.34

# Дефолтное число тем, опрашиваемых на комментарии одновременно.
# Параллелится только сетевой фетч; запись в БД остаётся последовательной.
COMMENT_FETCH_CONCURRENCY = 5

# Размеры страниц пагинации OK API.
# group.getStatTopics жёстко ограничивает count диапазоном [1..50].
TOPICS_PAGE_SIZE = 50
COMMENTS_PAGE_SIZE = 100
# mediatopic.getByIds ограничивает пачку; берём консервативный размер.
MEDIATOPIC_BATCH_SIZE = 20

# Коды ошибок OK API (https://apiok.ru/dev/errors).
OK_SERVICE_ERROR_CODE = 2
OK_PERMISSION_DENIED_CODE = 200
# GROUP_RESTRICTION: errors.group.cannot_view_stats — токен не администратор
# группы, статистика недоступна.
OK_GROUP_RESTRICTION_CODE = 456
# Ошибки, при которых стену/комментарии просто не отдают: не валим импорт,
# а пишем note. 200 — нет прав (не админ группы), 400/401 — сессия/доступ.
OK_ACCESS_DENIED_CODES = {OK_PERMISSION_DENIED_CODE, 400, 401}
# Коды, при которых список тем добываем фолбэком из публичной ленты.
OK_STATS_UNAVAILABLE_CODES = OK_ACCESS_DENIED_CODES | {OK_GROUP_RESTRICTION_CODE}

# Публичная мобильная версия OK — источник id тем, когда статистика закрыта.
OK_MOBILE_BASE = "https://m.ok.ru"
# С усечённым User-Agent m.ok.ru отдаёт заглушку без ленты — нужен полный
# мобильный Chrome (проверено вживую: короткий UA -> 46 КБ без тем,
# полный -> 220+ КБ с темами).
OK_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; SM-G970F) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
# Предохранитель пагинации публичной ленты (страница ~ 10-20 тем).
OK_MOBILE_MAX_PAGES = 300

# Тип обсуждения для комментариев к теме группы (ApiDiscussionType).
GROUP_TOPIC_DISCUSSION_TYPE = "GROUP_TOPIC"

# Поля group.getInfo, которых хватает для карточки паблика.
OK_GROUP_FIELDS = "uid,name,description,shortname,members_count,pic_avatar,access_type"

# Поля group.getStatTopics — id темы + агрегаты, из которых считаем метрики.
OK_STAT_TOPIC_FIELDS = (
    "id,external_id,created_ms,comments,likes,reshares,views,reach,engagement"
)

# FieldSet mediatopic.getByIds: сам топик + автор.
OK_MEDIATOPIC_FIELDS = "media_topic.*"

# Служебные разделы ok.ru, которые не являются группой/профилем.
RESERVED_PATHS = {
    "feed", "messages", "discussions", "guests", "friends", "video",
    "music", "games", "apps", "search", "settings", "help", "dk",
    "notifications", "photos", "groups", "live", "market", "vitrine",
}
