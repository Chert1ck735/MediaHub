"""Извлечение и нормализация адресных «кейсов» из текста (без БД/LLM/сети)."""
from __future__ import annotations

import re

from backend.modules.analytics.utils.text_normalize import (
    normalized_lookup_text,
    trim_text,
)


# Названия категорий/подкатегорий из таксономии. LLM иногда кладёт их в поле
# `case` вместо реального адресного кейса — такие значения отбрасываются,
# иначе они засоряют top_cases у других болей.
TAXONOMY_LABELS: set[str] = {
    # categories
    "жкх и городская среда",
    "дороги и транспорт",
    "экология и санитарное состояние",
    "социальная сфера",
    "управление и обратная связь",
    "безопасность и чс",
    "экономика торговля и регулирование",
    # subcategories
    "вывоз мусора", "отопление", "водоснабжение",
    "благоустройство и общественные пространства",
    "управляющая компания", "электроснабжение", "капитальный ремонт",
    "качество дорог", "ливневки и водоотвод", "общественный транспорт",
    "тротуары", "освещение", "парковка", "весовой контроль и большегрузы",
    "свалки и мусор", "качество воздуха", "загрязнение воды", "санитарное состояние",
    "медицина", "школы и детсады", "социальные выплаты и льготы",
    "социальные услуги", "доступная среда и помощь инвалидам",
    "помощь инвалидам и доступная среда",  # альтернативный порядок
    "спорт и досуг",
    "ответы ведомств", "сроки решений", "работа чиновников", "информирование жителей",
    "аварии и происшествия", "опасные объекты и участки", "экстренная реакция",
    "нарушения торговли", "контроль и лицензирование", "тарифы и цены",
    "мобильная связь", "мобильный интернет", "проводной интернет и ВОЛС",
    "тарифы операторов связи", "ограничения интернета",
    "цифровые услуги и госуслуги", "зоны без покрытия",
}


# Слишком общие топонимы — это «название всего региона» / «название страны»,
# не реальный адресный кейс. LLM любит их подставлять, когда не видит более
# конкретного объекта. Тогда case вообще не должен заполняться.
OVERLY_GENERAL_LOCATIONS: set[str] = {
    "красноярский край", "красноярский кр", "край",
    "россия", "российская федерация", "рф",
    "сибирь", "сибирский федеральный округ", "сфо",
    "москва", "санкт-петербург", "спб",
    "наш край", "наш регион", "наша страна", "наш район",
    "город красноярск", "г. красноярск", "г красноярск", "красноярск",
}


# Regex для извлечения локации из свободного текста. Требования:
#   * короткие сокращения (п, с, г, д, ул, пр, пер, бул, мкр, р-н) только с точкой;
#   * после префикса — заглавная буква собственного имени;
#   * длина собственного имени ≥ 4 символов;
#   * без IGNORECASE (capitalization-check).
# Длинные слова (посёлок, село, деревня, улица, город, район) допустимы в
# любом регистре, но следующее слово должно начинаться с заглавной.
CASE_PATTERN = re.compile(
    r"(?:"
    # Вариант 1: сокращение с точкой
    r"(?:п\.|пос\.|с\.|г\.|д\.|пгт\.|мкр\.|ул\.|пр\.|пр-кт\.|пр-т\.|пер\.|"
    r"бул\.|кв-л|пл\.|наб\.|шоссе|р-н)"
    r"\s*"
    r"[А-ЯЁ][а-яё\-]{3,}"
    r"(?:\s+[А-ЯЁ][а-яё\-]{2,})?"
    r")"
    r"|"
    r"(?:"
    # Вариант 2: полное слово в любом падеже
    r"(?:[Пп]осёлк[еауом]?|[Пп]оселк[еауом]?|[Сс]ел[аеуом]?|[Дд]еревн[еияую]|"
    r"[Гг]ород[еауом]?|[Уу]лиц[еауы]?|[Пп]ереул[ке][еа]?|"
    r"[Шш]оссе|[Нн]абережн[оая][йя]?|[Бб]ульвар[еауом]?|[Пп]лощад[еияью]|"
    r"[Кк]вартал[еауом]?|[Мм]икрорайон[еауом]?|"
    r"[Рр]айон[еауом]?|[Кк]ра[йеяю][еюм]?|[Оо]бласт[еияью])"
    r"\s+"
    r"[А-ЯЁ][а-яё\-]{3,}"
    r"(?:\s+[А-ЯЁ][а-яё\-]{2,})?"
    r")"
    r"|"
    r"(?:"
    # Вариант 3: постпозиция — "Курагинский район", "Красноярский край"
    r"[А-ЯЁ][а-яё\-]{4,}(?:ий|ой|ый|ская|ский|ское|ская)"
    r"\s+(?:район|край|область|округ|муниципалитет)"
    r")"
)


CASE_STOPWORDS: set[str] = {
    "и", "в", "во", "на", "к", "ко", "с", "со", "от", "для", "по", "за", "из",
    "у", "о", "об", "обо", "как", "что", "это", "там", "тут", "мы", "вы", "они",
    "он", "она", "оно", "наш", "ваш", "их", "мой", "твой", "свой", "если", "ли",
    "же", "бы", "уж", "очень", "просто", "все", "всё", "ещё", "уже", "тоже",
    "над", "под", "при", "после", "до", "без", "через", "про", "такой", "такая",
    "такие", "такое", "данный", "данная", "данные", "данное", "который",
    "которая", "которые", "которое", "господа", "уважаемый", "уважаемая",
    "уважаемые", "здравствуйте", "добрый", "пожалуйста", "спасибо", "михаил",
    "матвиенко", "викторович", "викторовна", "иванович",
}


CASE_LOCATION_MARKERS: tuple[str, ...] = (
    "норильск", "дудинк", "красноярск", "железногорск", "солонц", "ачинск",
    "канск", "арктич", "крайн", "север", "край", "город", "район", "посел",
    "пос.", "пос ", "мкр",
)


# (family_key, family_title, keywords). Если хоть один keyword найден в
# тексте, то кейс относится к этой «семье» — это используется для группировки
# близких комментариев в одну боль.
CASE_FAMILY_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "arctic_resettlement",
        "Переселение с Крайнего Севера",
        ("пересел", "арктич", "крайн", "север", "нориль", "дудин", "пенсионер", "реновац"),
    ),
    (
        "housing_tariffs",
        "Тарифы и начисления ЖКХ",
        ("тариф", "начислен", "квартплат", "платеж", "капремонт", "жкх", "коммун"),
    ),
    (
        "official_response",
        "Ответы ведомств",
        ("отписк", "не отвеч", "в соответствии с", "федерального закона", "сообщаем", "информируем", "разъясняем"),
    ),
    (
        "disability_support",
        "Помощь инвалидам и доступная среда",
        ("инвалид", "маломобиль", "коляс", "костыл", "доступн", "сопровожда"),
    ),
    (
        "safety_incident",
        "Безопасность и ЧС",
        ("обвал", "авари", "дтп", "происшеств", "погиб", "пострад", "чс", "угроз", "аварийн"),
    ),
    (
        "trade_control",
        "Торговля и регулирование",
        ("магазин", "алкогол", "торгов", "продаж", "лиценз", "контроль", "нарушен", "провер"),
    ),
    (
        "medical_access",
        "Медицина и доступ к помощи",
        ("больниц", "поликлиник", "врач", "кгбуз", "рб", "медицин", "скорая"),
    ),
)


# Сокращение + прилагательное/местоимение — частый regex-false-positive
# вида "д. Уголовной", "д. Нашу". Не локация, а обрезок предложения.
PRONOUN_TAILS: set[str] = {
    "нашу", "наш", "наша", "наше", "наши", "этот", "это", "эта", "эти", "этих",
    "тот", "та", "те", "тех", "сам", "сама", "сами", "какой", "какая", "какое",
    "какие", "любой", "любая", "любое", "ваш", "ваша", "ваши", "мой", "моя",
    # обычные слова предложения после «с./д./г.» — не топонимы
    "когда", "нужно", "надо", "сегодня", "завтра", "вчера", "почему", "зачем",
    "можно", "будет", "была", "были", "есть", "нету", "встречались", "значит",
    "просто", "конечно", "добрый", "доброе", "здравствуйте", "спасибо",
    # союзы и вводные: модель принимает конец предложения за префикс адреса —
    # «стим-ул. Однако, ...» превращается в «ул. Однако».
    "однако", "впрочем", "поэтому", "потому", "кстати", "например", "также",
    "хотя", "причем", "притом", "итак", "вообще", "далее", "затем", "теперь",
    "видимо", "наверное", "возможно", "правда", "разве", "неужели",
}


def infer_category(title: str) -> str | None:
    """Очень грубая первичная категоризация по ключевым словам в заголовке."""

    low = title.lower()
    if any(token in low for token in ("чс", "авар", "обвал", "погиб", "смерт", "угроз", "дтп", "аварийн")):
        return "Безопасность и ЧС"
    if any(token in low for token in ("магазин", "алкогол", "торгов", "продаж", "лиценз")):
        return "Экономика, торговля и регулирование"
    if any(token in low for token in ("отоп", "коммун", "водоснаб", "ук", "жк", "благоуст", "двор", "парк")):
        return "ЖКХ и городская среда"
    if any(token in low for token in ("дорог", "ремонт", "грузовик", "транспорт")):
        return "Дороги и транспорт"
    if any(token in low for token in ("социал", "специалист", "детск", "учрежден", "медицин", "инвалид")):
        return "Социальная сфера"
    if any(token in low for token in ("эколог", "воздух", "мусор")):
        return "Экология и санитарное состояние"
    return None


def looks_like_taxonomy_label(value: str) -> bool:
    """Похоже ли значение на имя категории/подкатегории, а не на реальный кейс."""

    norm = normalized_lookup_text(value)
    if not norm:
        return True
    if norm in TAXONOMY_LABELS:
        return True
    for label in TAXONOMY_LABELS:
        if len(norm) >= 6 and (norm in label or label in norm):
            return True
    return False


def extract_case_from_text(text: str, max_len: int = 120) -> str:
    """Regex-fallback: вытащить из комментария первую внятную локацию.

    Лучше упустить пограничный случай, чем заполнить case мусором
    («с этим сталкивалась» — это не локация).
    """

    if not text:
        return ""
    m = CASE_PATTERN.search(text[:1500])
    if not m:
        return ""
    candidate = m.group(0).strip().strip(",;.")
    if len(candidate) < 8:
        return ""
    if looks_like_taxonomy_label(candidate):
        return ""
    return candidate[:max_len]


def normalize_case(
    case_name: str,
    *,
    category: str,
    subcategory: str,
    source_text: str = "",
) -> str:
    """Очищает имя кейса и при необходимости заменяет его извлечением из текста."""

    clean_case = trim_text(case_name, 180)
    if clean_case:
        normalized_case = normalized_lookup_text(clean_case)
        if normalized_case in {normalized_lookup_text(category), normalized_lookup_text(subcategory)}:
            clean_case = ""
        elif looks_like_taxonomy_label(clean_case):
            clean_case = ""
    if not clean_case and source_text:
        clean_case = extract_case_from_text(source_text)
    return clean_case


def case_lookup_text(value: str) -> str:
    """Приводит строку к виду, удобному для поиска по семьям/маркерам."""

    text = normalized_lookup_text(value)
    text = re.sub(r"\[[^\]|]+\|([^\]]+)\]", r"\1", text)
    return text.replace("ё", "е")


def extract_case_routes(text: str) -> list[str]:
    """Находит пары вида "город-город" (маршрут), нормализует к "alpha:beta"."""

    routes: list[str] = []
    for left, right in re.findall(
        r"\b([a-zа-я]{3,})\s*[-–—]\s*([a-zа-я]{3,})\b",
        text,
    ):
        if left == right:
            continue
        routes.append(":".join(sorted((left, right))))
    return routes


def normalize_street_name(value: str) -> str:
    """Приводит склонение улицы к именительному падежу женского рода."""

    if value.endswith("ую"):
        return f"{value[:-2]}ая"
    if value.endswith("ой"):
        return f"{value[:-2]}ая"
    return value


def extract_case_streets(text: str) -> list[str]:
    """Извлекает названия улиц из текста (поддерживает варианты «ул. X и Y»)."""

    street_names: set[str] = set()
    street_marker = r"(?:\b(?:улица|ул)(?:\.|\b)\s+)"
    street_pattern = street_marker + r"([a-z0-9а-я-]{3,})"
    for match in re.finditer(street_pattern, text):
        street_names.add(normalize_street_name(match.group(1)))

    paired_pattern = (
        street_marker +
        r"[a-z0-9а-я-]{3,}(?:\s+(?:и|плюс)\s+|\s*[+/]\s*)"
        r"([a-z0-9а-я-]{3,})"
    )
    for match in re.finditer(paired_pattern, text):
        street_names.add(normalize_street_name(match.group(1)))

    slash_pair_pattern = r"\b([a-zа-я]{4,})\s*(?:/|\+)\s*([a-zа-я]{4,})\b"
    if not street_names:
        for left, right in re.findall(slash_pair_pattern, text):
            street_names.update((normalize_street_name(left), normalize_street_name(right)))

    return sorted(street_names)


def case_family_from_text(text: str) -> tuple[str, str] | None:
    """Если в тексте есть ключевые слова известной семьи — возвращает (key, title)."""

    low = case_lookup_text(text)
    if not low:
        return None
    for family_key, family_title, keywords in CASE_FAMILY_RULES:
        if any(keyword in low for keyword in keywords):
            return family_key, family_title
    return None


def case_semantic_signature(text: str) -> str:
    """Семантический отпечаток текста: до 8 значимых токенов через двоеточие.

    Стоп-слова и токены-локации отбрасываются, поэтому два разных
    комментария про одну и ту же боль (но с разной обвязкой) получат
    одинаковый отпечаток.
    """

    normalized = case_lookup_text(text)
    normalized = re.sub(r"\[[^\]]+\]", " ", normalized)
    normalized = re.sub(r"[^a-z0-9а-я]+", " ", normalized)
    tokens: list[str] = []
    for raw_token in normalized.split():
        token = normalize_street_name(raw_token)
        if len(token) < 3 or token in CASE_STOPWORDS:
            continue
        if any(marker in token for marker in CASE_LOCATION_MARKERS):
            continue
        if token.isdigit():
            continue
        tokens.append(token)

    if not tokens:
        return re.sub(r"[^a-z0-9а-я]+", " ", normalized).strip()

    compact: list[str] = []
    for token in tokens:
        if token not in compact:
            compact.append(token)
        if len(compact) >= 8:
            break
    return ":".join(compact)


def case_display_title(case_name: str, source_text: str) -> str:
    """Название кейса: РЕАЛЬНАЯ локация → семья → имя кейса → выдержка.

    Адресный кейс — это конкретное место. Если в case_name есть валидный адрес,
    показываем его, а НЕ тематическую «семью»: иначе жалоба про связь в северном
    посёлке (матч по слову «север»/«переселение») превращалась в «Переселение с
    Крайнего Севера» и засоряла адресные кейсы чужой темой.
    """

    clean_case = trim_text(case_name, 180)
    if clean_case and is_valid_case_title(clean_case):
        return clean_case
    family = case_family_from_text(f"{case_name} {source_text}")
    if family:
        return family[1]
    if clean_case:
        return clean_case
    return trim_text(source_text, 180)


def extract_case_house_numbers(text: str, streets: list[str]) -> list[str]:
    """Находит номера домов, упомянутые рядом с уже извлечёнными улицами."""

    if not streets:
        return []
    numbers: set[str] = set()
    for street in streets:
        pattern = rf"\b{re.escape(street)}\b\s*((?:\d+[a-zа-я]?\s*(?:,|\s+и\s+|\s*)?){{1,6}})"
        for match in re.finditer(pattern, text):
            numbers.update(re.findall(r"\d+[a-zа-я]?", match.group(1)))
    return sorted(numbers)


def case_dedupe_key(case_name: str, source_text: str) -> str:
    """Формирует ключ дедупликации.

    Приоритет: семья > улицы (+дома) > маршрут > семантический отпечаток.
    Если двум комментариям достался одинаковый ключ — это «одна боль»,
    их не считать как два упоминания.
    """

    case_text = case_lookup_text(case_name)
    text = case_lookup_text(f"{case_name} {source_text}")
    family = case_family_from_text(f"{case_name} {source_text}")
    if family:
        return f"family:{family[0]}"

    streets = extract_case_streets(text)
    if streets:
        house_numbers = extract_case_house_numbers(text, streets)
        suffix = f":houses:{','.join(house_numbers)}" if house_numbers else ""
        return f"streets:{','.join(streets)}{suffix}"

    routes = extract_case_routes(case_text)
    if not routes and any(marker in text for marker in (
        "трасса",
        "автодорога",
    )):
        routes = extract_case_routes(text)
    if routes:
        return f"route:{routes[0]}"

    return f"text:{case_semantic_signature(text)}"


_CASE_TYPE_WORDS: set[str] = {
    "село", "сел", "деревня", "дер", "посёлок", "поселок", "пос", "город", "гор",
    "край", "область", "обл", "округ", "район", "рн", "муниципалитет", "мо",
    "станция", "ст", "имени", "им", "улица", "ул", "микрорайон", "мкр",
}
# Лёгкий стемминг: срезаем хвост склонения/прилагательного, чтобы
# «рыбинский»/«рыбинского» и «успенка»/«успенке» сходились к одному корню.
_CASE_SUFFIXES: tuple[str, ...] = (
    "ого", "его", "ому", "ему", "ыми", "ими", "ая", "яя", "ое", "ее", "ой",
    "ый", "ий", "ом", "ем", "ах", "ях", "ов", "ев", "ке", "ку", "ка", "ы",
    "и", "а", "е", "у", "ю", "о",
)


def _case_stem(token: str) -> str:
    for suf in _CASE_SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 4:
            return token[: -len(suf)]
    return token


# Тип-слова в любом падеже («района», «области») — фильтруем и после стемминга.
_CASE_TYPE_STEMS: set[str] = _CASE_TYPE_WORDS | {_case_stem(w) for w in _CASE_TYPE_WORDS}


def case_location_key(title: str) -> str:
    """Канонический ключ локации для дедупа адресных кейсов.

    «с. Успенка, Рыбинский район», «село Успенка Рыбинского района» и
    «село Успенка, Рыбинский район, Красноярский край» дают ОДИН ключ.
    Срезаем тип-слова (село/посёлок/район/край…), общий регион и приводим
    оставшиеся токены к корню (лёгкий стемминг склонений). Универсально для
    любого паблика. Пустая строка — если осмысленной локации не осталось.
    """

    s = case_lookup_text(title)  # lower, ё→е, раскрытие vk-упоминаний
    s = s.replace("красноярский край", " ").replace("красноярского края", " ")
    s = re.sub(r"[^a-zа-я0-9]+", " ", s)
    stems: list[str] = []
    houses: list[str] = []
    for tok in s.split():
        if re.fullmatch(r"\d+[a-zа-я]?", tok):
            houses.append(tok)
            continue
        if tok in _CASE_TYPE_WORDS or len(tok) < 3:
            continue
        st = _case_stem(tok)
        if st in _CASE_TYPE_STEMS or len(st) < 3:
            continue
        stems.append(st)
    key = " ".join(sorted(set(stems)))
    if key and houses:
        key = f"{key} {' '.join(sorted(set(houses)))}"
    return key


# Открывашки-не-адрес: фразы с заглавной, которые не являются адресом/топонимом.
CASE_STOP_OPENERS = {
    "спасибо", "благодарю", "благодарность", "молодцы", "молодец", "браво", "ура",
    "очень", "просто", "конечно", "почему", "зачем", "что", "как", "когда", "где",
    "это", "эти", "вот", "нет", "да", "хорошо", "плохо", "ужас", "кошмар", "класс",
    "супер", "жаль", "увы", "добрый", "здравствуйте", "привет", "пожалуйста", "прошу",
    "хочу", "мечтаю", "отлично", "замечательно", "прекрасно", "отличная", "замечательная",
    "хорошая", "плохая", "надо", "нужно", "давайте", "давай", "думаю", "считаю",
}
_PLACE_WORDS = (
    "школа", "село", "посёлок", "поселок", "деревня", "город", "улица", "переулок",
    "набережная", "бульвар", "площадь", "квартал", "микрорайон", "район", "край",
    "область", "округ", "парк", "больница", "поликлиника", "церковь", "храм",
    "проспект", "дом", "детсад", "садик", "гимназия", "лицей",
)
_PLACE_STARTS = (
    "ул.", "г.", "с.", "д.", "п.", "пр.", "пер.", "пос.", "мкр.", "наб.", "пл.",
    "пгт.", "р-н", *_PLACE_WORDS,
)
_PLACE_ABBR = {"д", "с", "п", "г", "пос", "пгт", "ул", "пр", "пер", "мкр", "наб", "пл"}
_PLACE_PREFIX_TOKENS = {f"{abbr}." for abbr in _PLACE_ABBR}

# Линейные и природные объекты: точкой на карте их не показать.
_ROUTE_MARKERS = ("маршрут", "рейс", "автобус №", "маршрутк")
_NATURAL_OBJECTS = {
    "енисей", "ангара", "кан", "чулым", "мана", "абакан", "бирюса", "тасеева",
    "подкаменная тунгуска", "нижняя тунгуска", "кача", "базаиха", "есауловка",
}
# Формулировки «везде и нигде»: конкретного места нет.
_VAGUE_STARTS = ("по всему", "по всем", "во всем", "во всём", "вокруг", "везде", "повсюду")
_VAGUE_MARKERS = ("наша улица", "нашей улице", "нашу улицу", "наш двор", "нашем дворе")
# «поликлиники города», «школы района» — объекты во множественном числе без имени.
_VAGUE_PLURAL = re.compile(r"^[а-яё]+[иы]\s+(города|района|округа|края)$")
# Обрывок названия площадки в родительном падеже: «города Минусинска».
_PUBLIC_FRAGMENT = re.compile(r"^(город[аеу]\s+[а-яё-]+|[а-яё-]+ого\s+(округа|района))$")
_CHAIN_STREET = re.compile(
    r"\b(ул|улица|пер|переулок|пр|проспект|проезд|шоссе|тракт|наб|набережная)\b\.?",
    re.I,
)


def _looks_like_address_chain(title: str) -> bool:
    """Иерархия «от большего к меньшему», а не перечисление однотипных объектов."""
    parts = [part.strip() for part in title.split(",") if part.strip()]
    streets = sum(1 for part in parts if _CHAIN_STREET.search(part))
    if streets > 1:
        return False
    has_house = any(any(ch.isdigit() for ch in part) for part in parts)
    return streets == 1 and has_house
# Названия организаций/страны — это не адрес («д. Минздрав России»).
_ORG_MARKERS = (
    "министерств", "минздрав", "минсоц", "минфин", "минстрой", "минцифры", "ведомств",
    "департамент", "агентство", "росприроднадзор", "роспотребнадзор", "россии", "российск",
)


def is_valid_case_title(title: str) -> bool:
    """Проверяет, выглядит ли строка как осмысленная адресная привязка.

    Отсекает: короткие куски, taxonomy-имена, слишком длинные «эссе»,
    обрезки вида «д. Какой» / «с. Нашу», слишком общие топонимы
    (название всего региона/страны).
    """

    s = title.strip()
    if len(s) < 4:
        return False
    if looks_like_taxonomy_label(s):
        return False
    # Плейсхолдеры вместо реального адреса: «ул. Не указана», «адрес неизвестен»,
    # «нет данных» — LLM так помечает, когда конкретики нет. Это не кейс.
    low = normalized_lookup_text(s)
    if any(ph in low for ph in (
        "не указан", "не указана", "не указано", "не указаны",
        "неизвестн", "отсутствует", "нет данных", "не определен",
    )):
        return False
    # Тематические «семьи» (Переселение с Крайнего Севера, Тарифы ЖКХ и т.п.) —
    # это группировка по теме, а не адрес. В список адресных кейсов им не место.
    if low in {normalized_lookup_text(t) for _k, t, _kw in CASE_FAMILY_RULES}:
        return False
    # Названия региона/страны целиком — это не кейс.
    if normalized_lookup_text(s) in OVERLY_GENERAL_LOCATIONS:
        return False
    # Голый тип места без имени: «посёлок», «район», «город».
    if low in {normalized_lookup_text(w) for w in _PLACE_WORDS}:
        return False
    # Маршрут — линия между точками, на карте одной точкой не показывается.
    if any(marker in low for marker in _ROUTE_MARKERS):
        return False
    # Река или иной природный объект: «Енисей» тянется через полкрая.
    if low in _NATURAL_OBJECTS:
        return False
    # «по всему городу», «наша улица» — места нет ни у кого, кроме автора.
    if low.startswith(_VAGUE_STARTS) or any(marker in low for marker in _VAGUE_MARKERS):
        return False
    if _VAGUE_PLURAL.match(low):
        return False
    # Остаток обращения к паблику. Именительный падеж («город Минусинск»)
    # остаётся адресом, родительный («города Минусинска») — нет.
    if _PUBLIC_FRAGMENT.match(low):
        return False
    # Плейс-префикс + название организации/страны: «д. Минздрав России».
    _tok = low.replace(".", " ").split()
    if _tok and _tok[0] in _PLACE_ABBR and any(mk in " ".join(_tok[1:]) for mk in _ORG_MARKERS):
        return False
    if len(s) > 120:
        return False
    # Много запятых — обычно перечисление («пер. Алгасинский, пер. Пятилетки»),
    # но так же выглядит и полная иерархия («край, округ, село, улица, дом»).
    # Перечисление выдаёт повтор одного и того же типа объекта.
    if s.count(",") >= 4 and not _looks_like_address_chain(s):
        return False
    parts = s.lower().split(maxsplit=1)
    if len(parts) == 2 and parts[0] in _PLACE_PREFIX_TOKENS:
        second = parts[1].strip(",;.").split(maxsplit=1)[0]
        if second in PRONOUN_TAILS:
            return False
    first = s[0]
    if first.isdigit():
        return True
    low = s.lower()
    if first.isupper():
        opener = low.split()[0].strip(".,!?;:—-«»()\"'") if low.split() else ""
        if opener in CASE_STOP_OPENERS:
            return False
        # адресный признак: номер дома, слово-место, ≥2 заглавных слова
        # (собственное имя) или единственное слово-топоним
        has_digit = any(ch.isdigit() for ch in s)
        has_place = any(w in low for w in _PLACE_WORDS)
        caps_words = sum(1 for w in s.split() if w[:1].isupper())
        return has_digit or has_place or caps_words >= 2 or len(low.split()) == 1
    # строчные: адрес по префиксу, ИЛИ есть слово-место/номер дома где-то внутри
    return (any(low.startswith(pref) for pref in _PLACE_STARTS)
            or any(w in low for w in _PLACE_WORDS)
            or any(ch.isdigit() for ch in s))
