"""Deterministic display normalization for address cases.

The raw case value is still the durable key for comments and drill-down. This
module only builds a stable human-facing title for cards and map points.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from backend.modules.analytics.utils.text_normalize import trim_text


_LEADING_NOISE_RE = re.compile(
    r"^(?:по\s+адресу|адрес|в\s+районе|район|возле|около|рядом\s+с|у|на|по)\s+",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")
_PUNCT_SPACE_RE = re.compile(r"\s*([,;:])\s*")
_HOUSE_RE = r"\d+[а-яa-z0-9/-]*"


def _clean(value: str) -> str:
    text = trim_text(value or "", 180)
    text = text.strip(" \t\r\n\"'«».,;:")
    text = re.sub(r"\b(?:д\.?|дом)\s*(?=\d)", "", text, flags=re.IGNORECASE)
    # «Пер.медицинский» — сокращение слиплось с названием улицы.
    text = re.sub(
        r"\b(ул|пер|пр|просп|наб|мкр|ш)\.(?=[а-яёa-z])",
        r"\1. ",
        text,
        flags=re.IGNORECASE,
    )
    # «ул. Вавилова, г Красноярск» и «ул. Ленина, Красноярск» — один город
    # в двух видах. Приводим к одному: тип «г»/«город» перед названием
    # ничего не уточняет, в отличие от «село» или «посёлок».
    text = re.sub(
        r"(^|,\s*)(?:г|гор|город)\.?\s+(?=[А-ЯЁA-Z])",
        r"\1",
        text,
    )
    text = text.replace("№", " №")
    text = _PUNCT_SPACE_RE.sub(r"\1 ", text)
    text = _SPACE_RE.sub(" ", text).strip(" ,;:")
    previous = None
    while text and previous != text:
        previous = text
        text = _LEADING_NOISE_RE.sub("", text).strip(" ,;:")
    return text


def _title_words(value: str) -> str:
    keep_lower = {"и", "им", "им.", "на", "при"}
    parts: list[str] = []
    for token in value.split():
        if token.lower() in keep_lower:
            parts.append(token.lower().rstrip("."))
            continue
        if token.isupper() and len(token) <= 4:
            parts.append(token)
            continue
        chunks = []
        for chunk in token.split("-"):
            chunks.append(chunk[:1].upper() + chunk[1:].lower() if chunk else chunk)
        parts.append("-".join(chunks))
    return " ".join(parts)


def _geo_value(geo: Mapping[str, object] | None, key: str) -> str:
    if not geo:
        return ""
    value = geo.get(key)
    return str(value or "").strip()


def _compact_admin(value: str) -> str:
    text = _clean(value)
    text = re.sub(r"^городской округ\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+муниципальный округ$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+муниципальный район$", "", text, flags=re.IGNORECASE)
    return text


def _locality_label(geo: Mapping[str, object] | None) -> str:
    locality = _compact_admin(_geo_value(geo, "locality"))
    municipality = _compact_admin(_geo_value(geo, "municipality"))
    if locality:
        return locality
    return municipality


def _append_location(title: str, geo: Mapping[str, object] | None) -> str:
    locality = _locality_label(geo)
    if not locality:
        return title
    low_title = title.lower()
    low_locality = locality.lower()
    if low_locality in low_title:
        return title
    return f"{title}, {locality}"


def _institution_title(text: str, geo: Mapping[str, object] | None) -> str | None:
    patterns = (
        (r"\b(?:сош|шк\.?|школ[ауы]?)(?:\s*(?:№|номер|n|#))?\s*(\d+[а-яa-z]?)\b", "школа"),
        (r"\b(?:детский\s+сад|детсад|садик|д/с)(?:\s*(?:№|номер|n|#))?\s*(\d+[а-яa-z]?)\b", "детский сад"),
        (r"\b(?:поликлиник[ауы]?)(?:\s*(?:№|номер|n|#))?\s*(\d+[а-яa-z]?)\b", "поликлиника"),
        (r"\b(?:больниц[ауы]?)(?:\s*(?:№|номер|n|#))?\s*(\d+[а-яa-z]?)\b", "больница"),
    )
    for pattern, label in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            number = match.group(1).upper()
            return _append_location(f"{label} №{number}", geo)
    return None


# Тип места перед названием: раньше любой из них становился «ул.», и
# «микрорайон Мирный» показывался как «ул. Мирный», а «проспект Котельникова»
# — как «ул. Котельникова».
_STREET_KIND = {
    "ул": "ул.", "улица": "ул.",
    "пер": "пер.", "переулок": "пер.",
    "проспект": "просп.", "пр-т": "просп.", "пр-кт": "просп.",
    "мкр": "мкр.", "микрорайон": "мкр.",
    "наб": "наб.", "набережная": "наб.",
    "бульвар": "бул.", "б-р": "бул.",
    "шоссе": "шоссе",
}


def _street_title(text: str, geo: Mapping[str, object] | None) -> str | None:
    marker = (
        r"(?:ул\.?|улица|проспект|пр-т|пр-кт|пер\.?|переулок|мкр\.?|микрорайон"
        r"|наб\.?|набережная|бульвар|б-р|шоссе)"
    )
    marked = re.search(
        rf"\b({marker})\s+([а-яёa-z0-9 .'-]{{2,70}}?)(?:[, ]+(?:{_HOUSE_RE})\b|$)",
        text,
        flags=re.IGNORECASE,
    )
    if marked:
        # «наб. 51» — это дом на Набережной, а не набережная номер 51.
        if not re.search(r"[а-яёa-z]", marked.group(2), re.IGNORECASE):
            marked = None
    if marked:
        kind = _STREET_KIND.get(marked.group(1).lower().rstrip("."), "ул.")
        name = marked.group(2).strip(" ,.;:")
        tail = text[marked.end(2):]
        house_match = re.search(rf"(?:^|[, ]+)(?:д\.?|дом)?\s*({_HOUSE_RE})\b", tail, flags=re.IGNORECASE)
        house = house_match.group(1).upper() if house_match else ""
        base = _title_words(name)
        if house:
            title = f"{base}, {house}"
            return _append_location(title, geo)
        # Улица без дома тоже нуждается в посёлке: «ул. Нагорная» есть в
        # Солонцах, Мазульском, Слизнево и Дивногорске, и без указания места
        # четыре разные улицы в списке выглядят одной строкой, повторённой
        # несколько раз.
        return _append_location(f"{kind} {base}", geo)

    bare = re.match(
        rf"^([а-яёa-z][а-яёa-z0-9 .'-]{{2,55}}?)[, ]+(?:д\.?|дом)?\s*({_HOUSE_RE})$",
        text,
        flags=re.IGNORECASE,
    )
    if bare:
        title = f"{_title_words(bare.group(1).strip(' ,.;:'))}, {bare.group(2).upper()}"
        return _append_location(title, geo)
    return None


# Пояснения, которые житель дописывает к адресу: «ул. Нагорная в Солонцах у
# складов Янта», «Бувайсара Сайтиева (от Молокова до Краснодарской)». Всё,
# что идёт после такой связки, к самому адресу не относится.
_TAIL_RE = re.compile(
    r"(?:\s+(?:до|от|у|в|во|около|возле|рядом|между|через|перед|за|напротив|и)\s+"
    r"|\s*[(/]|\s+[-–—]\s+)",
    re.IGNORECASE,
)

# Слово, с которого начинается название территории, а не адреса.
_PLACE_ONLY_RE = re.compile(
    r"^(?:зато\s+)?(?:г|город|гор|пгт|п|пос|пос[её]лок|с|село|д|деревня|ст|станция|"
    r"снт|район|округ|край|территория|центр)\b",
    re.IGNORECASE,
)

_STREET_MARKER_RE = re.compile(
    r"\b(?:ул|улиц\w*|просп\w*|пр-?кт|пр-?т|переул\w*|пер|шоссе|наб|набережн\w*|"
    r"бульвар|б-р|проезд|тракт|мкр|микрорайон|квартал|тупик|аллея)\b",
    re.IGNORECASE,
)
_HOUSE_NUMBER_RE = re.compile(r"(?:^|[\s,])\d{1,4}[а-яa-z]?(?:$|[\s,/])", re.IGNORECASE)


# Слова про устройство территории: сами по себе они места не называют.
_PLACE_NOISE_STEMS = frozenset({"зато", "пгт", "центр", "городск", "окраин", "черт"})


# Слова, которые сами по себе места не называют. Если после обрезки остаются
# только они, обрезать было нечего — уточнение и было адресом.
GENERIC_STEMS = frozenset({
    "дорог", "дорожк", "перекрест", "остановк", "мост", "двор", "тротуар",
    "проезд", "площад", "участок", "поворот", "съезд", "подъезд", "переход",
    "трасс", "развязк", "лестниц", "объезд", "вход", "заезд", "газон",
})


def _has_own_name(text: str) -> bool:
    """Осталось ли в названии что-то своё, кроме общих слов."""

    from backend.modules.analytics.utils.case_extractor import case_location_key

    stems = {token for token in case_location_key(text).split() if not token[:1].isdigit()}
    return bool(stems - GENERIC_STEMS)


def trim_address_tail(raw_title: str) -> str:
    """Отрезает пояснение, дописанное жителем после адреса.

    Но только если после обрезки остаётся собственное название. «Дорога между
    домами Киренского 116 и 118» без пояснения превращается в «Дорогу», и
    десяток разных мест выглядит одной строкой — там уточнение и есть адрес.
    """

    text = _clean(raw_title)
    match = _TAIL_RE.search(text)
    if not match or match.start() == 0:
        return text
    trimmed = text[: match.start()].strip(" ,.;:-")
    return trimmed if _has_own_name(trimmed) else text


def is_address_like(raw_title: str, geo: Mapping[str, object] | None = None) -> bool:
    """Адрес это или название территории.

    В списке «Адреса» глава ждёт улицу, дом или учреждение. «Город Дивногорск»
    и «ЗАТО г. Железногорск» — это территории: они не говорят, куда ехать.
    Территорию видно по тому, что от названия не остаётся ничего сверх самого
    населённого пункта, который вернул геокодер.
    """

    from backend.modules.analytics.utils.case_extractor import case_location_key

    text = trim_address_tail(raw_title)
    if not text:
        return False
    # Голый номер без улицы — «5, Красноярск». Ехать по нему некуда.
    if not re.search(r"[а-яa-z]", text, re.IGNORECASE):
        return False
    if _institution_title(text, geo):
        return True
    if _STREET_MARKER_RE.search(text) or _HOUSE_NUMBER_RE.search(text):
        return True

    place = " ".join(
        part
        for part in (_geo_value(geo, "locality"), _geo_value(geo, "municipality"))
        if part
    )
    if place:
        title_stems = set(case_location_key(text).split()) - _PLACE_NOISE_STEMS
        place_stems = set(case_location_key(place).split())
        # Стеммер режет склонения неровно: «Красноярска» даёт «красноярс», а
        # «Красноярск» — «красноярск». Сравниваем по началу слова.
        def _known(stem: str) -> bool:
            return any(
                stem.startswith(other) or other.startswith(stem)
                for other in place_stems
                if len(other) >= 4 and len(stem) >= 4
            )

        return bool(title_stems) and not all(_known(stem) for stem in title_stems)

    return not _PLACE_ONLY_RE.match(text)


_LEADING_KIND_RE = re.compile(
    r"^(Ул|Пер|Просп|Мкр|Наб|Бул)\.\s", re.IGNORECASE
)


def _lower_leading_kind(title: str) -> str:
    """Тип места в начале подписи — всегда строчными."""

    match = _LEADING_KIND_RE.match(title)
    return title[: match.end()].lower() + title[match.end():] if match else title


def address_display_title(raw_title: str, geo: Mapping[str, object] | None = None) -> str:
    """Единый заголовок для показа; сырой ключ кейса при этом не меняется."""

    text = trim_address_tail(raw_title)
    if not text:
        return ""

    institution = _institution_title(text, geo)
    if institution:
        return institution

    street = _street_title(text, geo)
    if street:
        return _lower_leading_kind(street)

    title = _title_words(text)
    if len(title) <= 32:
        return _lower_leading_kind(_append_location(title, geo))
    return _lower_leading_kind(title)


def address_canonical_title(raw_title: str, geo: Mapping[str, object] | None = None) -> str:
    """Более явный заголовок — для диагностики кэша и будущей склейки дублей."""

    display = address_display_title(raw_title, geo)
    locality = _locality_label(geo)
    if not display or not locality:
        return display
    if locality.lower() in display.lower():
        return display
    return f"{display}, {locality}"
