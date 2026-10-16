"""Константы VK-модуля."""

API_BASE = "https://api.vk.com/method"
MAX_RETRIES = 4
POSTING_MAX_RETRIES = 5
RETRY_DELAY_SEC = 1.5
POSTING_RETRY_DELAY_SEC = 2
INTER_REQUEST_DELAY_SEC = 0.34

# Дефолтное число постов, опрашиваемых на комментарии одновременно.
# Параллелится только сетевой фетч; запись в БД остаётся последовательной.
COMMENT_FETCH_CONCURRENCY = 5

NOT_FOUND_CODES = {15, 18, 100, 104, 113, 125, 203}
PRIVATE_CODES = {15, 30, 203}
VK_INVALID_TARGET_ERROR_CODES = {15, 100, 104, 125, 203}

# Метка авто-создаваемого дефолтного паблика (постинг-цель из GROUP_ID).
AUTO_DEFAULT_PUBLIC_DESCRIPTION = "Автоматически создано из GROUP_ID для дефолтной публикации"

VK_GROUP_FIELDS = "members_count,description,activity,site,screen_name,city,verified"
VK_USER_FIELDS = (
    "screen_name,first_name,last_name,can_access_closed,is_closed,"
    "sex,city,country,about,bdate,counters,followers_count"
)

RESERVED_PATHS = {
    "feed", "im", "settings", "friends", "groups", "photos",
    "video", "audio", "messages", "search", "login", "support",
    "app", "apps", "market", "podcasts", "vkpay", "stickers", "stories",
}
