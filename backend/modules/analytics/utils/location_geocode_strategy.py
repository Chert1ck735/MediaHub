from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from backend.modules.analytics.utils.geocode import GeoPoint


REGION_CAPITALS = {
    "алтайский край": "Барнаул",
    "амурская область": "Благовещенск",
    "архангельская область": "Архангельск",
    "астраханская область": "Астрахань",
    "белгородская область": "Белгород",
    "брянская область": "Брянск",
    "владимирская область": "Владимир",
    "волгоградская область": "Волгоград",
    "вологодская область": "Вологда",
    "воронежская область": "Воронеж",
    "забайкальский край": "Чита",
    "иркутская область": "Иркутск",
    "калужская область": "Калуга",
    "краснодарский край": "Краснодар",
    "красноярский край": "Красноярск",
    "ленинградская область": "Санкт-Петербург",
    "липецкая область": "Липецк",
    "нижегородская область": "Нижний Новгород",
    "орловская область": "Орел",
    "республика адыгея": "Майкоп",
    "республика алтай": "Горно-Алтайск",
    "республика башкортостан": "Уфа",
    "самарская область": "Самара",
    "саратовская область": "Саратов",
    "свердловская область": "Екатеринбург",
    "тамбовская область": "Тамбов",
    "тверская область": "Тверь",
    "челябинская область": "Челябинск",
    "чувашская республика": "Чебоксары",
}


# Города, ЗАТО и райцентры Красноярского края: по ним определяем локалитет
# паблика из его названия («Новости Железногорска» → Железногорск), когда в
# самом кейсе города нет.
KRAI_LOCALITIES: tuple[str, ...] = (
    "Красноярск", "Норильск", "Ачинск", "Канск", "Железногорск", "Минусинск",
    "Зеленогорск", "Лесосибирск", "Назарово", "Шарыпово", "Сосновоборск",
    "Дивногорск", "Боготол", "Бородино", "Енисейск", "Дудинка", "Игарка",
    "Заозерный", "Кодинск", "Ужур", "Уяр", "Иланский", "Артемовск",
    "Кайеркан", "Талнах", "Солнечный", "Кедровый", "Подгорный",
    "Березовка", "Емельяново", "Курагино", "Шушенское", "Тура", "Байкит",
    "Богучаны", "Мотыгино", "Северо-Енисейский", "Туруханск", "Ермаковское",
    "Идринское", "Краснотуранск", "Новоселово", "Балахта", "Козулька",
    "Большая Мурта", "Сухобузимское", "Тасеево", "Дзержинское", "Абан",
    "Нижний Ингаш", "Ирбейское", "Партизанское", "Агинское", "Каратузское",
)

_MIN_STEM = 5

# Насколько стемы могут расходиться в длине. Падежные формы одного названия
# дают разницу максимум в пару символов («минусин»/«минусинск»), а совпадение
# корней разных слов — большую («зелен» из «улицы Зелёной» против
# «зеленогорск»). Без этой границы улицы-прилагательные становятся городами.
_MAX_STEM_GAP = 2

# Окончания падежных и прилагательных форм названия: «Дивногорска»,
# «Ачинского», «Шушенское». Список отсортирован от длинных к коротким.
_LOCALITY_ENDINGS = (
    "ского", "ские", "ский", "ская", "ское",
    "ому", "ого", "ым", "ом", "ой", "ая", "ое", "ый", "ий", "ые",
    "а", "е", "и", "о", "у", "ы",
)

_LOCALITY_STEMS: dict[str, str] = {}


def _locality_stem(value: str) -> str:
    token = norm_match(value).replace(" ", "")
    for ending in _LOCALITY_ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= _MIN_STEM:
            return token[: -len(ending)]
    return token


def _stems_match(left: str, right: str) -> bool:
    """Стем грубый — «Ачинского» даёт «ачин», «Ачинск» даёт «ачинск». Сравниваем по префиксу."""
    if not (left and right):
        return False
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    if len(long) - len(short) > _MAX_STEM_GAP:
        return False
    return len(short) >= _MIN_STEM and long.startswith(short)


def known_locality(phrase: str) -> str:
    """Название из справочника края, если фраза — его форма. Длинное совпадение приоритетнее."""
    if not _LOCALITY_STEMS:
        _LOCALITY_STEMS.update({_locality_stem(name): name for name in KRAI_LOCALITIES})
    stem = _locality_stem(phrase)
    plain = norm_match(phrase).replace(" ", "")
    best, best_len = "", 0
    for canon_stem, name in _LOCALITY_STEMS.items():
        # Короткие названия («Уяр», «Абан») стемминг не берёт — сравниваем как есть.
        matched = (
            _stems_match(stem, canon_stem)
            if len(canon_stem) >= _MIN_STEM
            else plain == canon_stem
        )
        if matched and len(canon_stem) > best_len:
            best, best_len = name, len(canon_stem)
    return best


def locality_from_public(*values: Any) -> str:
    """Локалитет из названия паблика: «Администрация города Дивногорска» → Дивногорск."""
    for value in values:
        tokens = norm_match(value).split()
        # Составные названия проверяем раньше одиночных слов, иначе
        # «Северо-Енисейского» матчится на Енисейск.
        for size in (2, 1):
            for start in range(len(tokens) - size + 1):
                found = known_locality(" ".join(tokens[start : start + size]))
                # Столицу не берём: у краевых пабликов «Красноярск» в названии не
                # означает, что жалоба про город.
                if found and found != "Красноярск":
                    return found
    return ""


@dataclass(frozen=True)
class LocationContext:
    case_name: str
    public_region: str = ""
    public_name: str = ""
    source_title: str = ""
    comment_text: str = ""
    address: str = ""
    address_hierarchy: Mapping[str, Any] | None = None


def norm(value: Any) -> str:
    return str(value or "").strip()


def norm_match(value: Any) -> str:
    text = norm(value).lower().replace("ё", "е")
    for char in "\"'«».,;:()[]{}!?—–-/":
        text = text.replace(char, " ")
    return " ".join(text.split())


def important_tokens(value: Any) -> set[str]:
    stop_words = {
        "г",
        "город",
        "край",
        "область",
        "республика",
        "район",
        "округ",
        "муниципальный",
        "муниципального",
        "област",
    }
    return {
        token
        for token in norm_match(value).split()
        if len(token) >= 4 and token not in stop_words
    }


def region_capital(region: Any) -> str:
    return REGION_CAPITALS.get(norm_match(region), "")


def _hierarchy_text(ctx: LocationContext) -> str:
    data = ctx.address_hierarchy
    if not isinstance(data, Mapping):
        return ""
    return " ".join(str(value or "") for value in data.values())


def _hierarchy_get(ctx: LocationContext, *keys: str) -> str:
    data = ctx.address_hierarchy
    if not isinstance(data, Mapping):
        return ""
    for key in keys:
        value = norm(data.get(key))
        if value:
            return value
    return ""


def infer_effective_region(ctx: LocationContext) -> str:
    if norm(ctx.public_region):
        return norm(ctx.public_region)
    hierarchy_region = _hierarchy_get(ctx, "region")
    if hierarchy_region:
        return hierarchy_region
    blob = norm_match(
        " ".join(
            [
                ctx.public_name,
                ctx.source_title,
                ctx.comment_text,
                ctx.case_name,
                ctx.address,
                _hierarchy_text(ctx),
            ]
        )
    )
    if "красноярск" in blob or "котюков" in blob:
        return "Красноярский край"
    explicit_regions = [
        ("ленобласти", "Ленинградская область"),
        ("ленинградская область", "Ленинградская область"),
        ("нижегородская область", "Нижегородская область"),
        ("тверская область", "Тверская область"),
        ("саратовская область", "Саратовская область"),
        ("краснодарский край", "Краснодарский край"),
        ("республика алтай", "Республика Алтай"),
        ("калужская область", "Калужская область"),
        ("орловская область", "Орловская область"),
        ("самарская область", "Самарская область"),
        ("республика адыгея", "Республика Адыгея"),
        ("чуваш", "Чувашская Республика"),
    ]
    for marker, value in explicit_regions:
        if marker in blob:
            return value
    return ""


def _query(region: str, value: str) -> str:
    if region and norm_match(region) not in norm_match(value):
        return f"{region}, {value}"
    return value


def _looks_like_street_or_house(value: str) -> bool:
    low = norm_match(value)
    street_markers = {
        "ул",
        "улица",
        "проспект",
        "проезд",
        "переулок",
        "шоссе",
        "тракт",
        "набережная",
        "дом",
    }
    if street_markers.intersection(low.split()):
        return True
    return bool(re.search(r"\bд(?:ом)?\s*\d", low) or re.search(r"\b[а-яё-]{5,}\s*,?\s*\d", low))


def _has_explicit_locality(value: str) -> bool:
    markers = {
        "г",
        "город",
        "село",
        "с",
        "поселок",
        "пос",
        "п",
        "пгт",
        "деревня",
        "д",
        "станица",
        "аул",
    }
    return bool(markers.intersection(norm_match(value).split()))


def _is_region_only_case(value: str) -> bool:
    low = norm_match(value)
    return bool(low) and (
        low.endswith(" область")
        or low.endswith(" край")
        or low.startswith("республика ")
    ) and not any(marker in low for marker in ("район", "округ", "улица", "ул ", "дом"))


def _add_unique(items: list[str], value: str) -> None:
    value = norm(value)
    if value and value not in items:
        items.append(value)


def _address_hierarchy_queries(ctx: LocationContext) -> list[str]:
    result: list[str] = []
    region = _hierarchy_get(ctx, "region")
    district = _hierarchy_get(ctx, "district")
    municipality = _hierarchy_get(ctx, "municipality")
    locality = _hierarchy_get(ctx, "locality")
    street = _hierarchy_get(ctx, "street")
    house = _hierarchy_get(ctx, "house")
    building = _hierarchy_get(ctx, "building")
    institution = _hierarchy_get(ctx, "institution")

    parts: list[str] = []
    for value in (region, district, municipality, locality):
        _add_unique(parts, value)
    street_part = ", ".join(part for part in (street, house, building) if part)
    _add_unique(parts, street_part)
    _add_unique(parts, institution)

    if len(parts) >= 2 or (parts and parts[0] != norm(ctx.case_name)):
        _add_unique(result, ", ".join(parts))
    if norm(ctx.address):
        _add_unique(result, norm(ctx.address))
    return result


def _owner_street_variant(value: str) -> str:
    match = re.match(
        r"^\s*(?P<street>.+?\b(?:улица|ул\.?|проспект|проезд|переулок|шоссе|тракт|набережная))"
        r"\s+(?P<owner>[А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z-]{4,})"
        r"(?P<rest>\s*,?\s*(?:дом|д\.?)?\s*\d.*)$",
        value,
        re.IGNORECASE,
    )
    if not match:
        return ""
    return ", ".join(
        part.strip(" ,.")
        for part in (match.group("owner"), match.group("street"), match.group("rest"))
        if part.strip(" ,.")
    )


def _case_rewrite_variants(case_name: str, *, region: str, comment_text: str) -> list[str]:
    text = norm(case_name)
    low = norm_match(text)
    result: list[str] = []

    normalized = re.sub(r"\bселе\b", "село", text, flags=re.IGNORECASE)
    normalized = re.sub(r"\bпос[её]лке\b", "поселок", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bмкр\.\s*", "микрорайон ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    if normalized != text:
        _add_unique(result, normalized)

    match = re.search(r"\b(?:мост|здание)\s+(?:по|на)\s+([А-ЯЁ][а-яё-]{4,})", text, re.IGNORECASE)
    if match:
        _add_unique(result, f"улица {match.group(1)}")
    match = re.search(r"\b(?:мост|здание)\s+([А-ЯЁ][а-яё-]{4,})", text, re.IGNORECASE)
    if match:
        _add_unique(result, f"улица {match.group(1)}")

    match = re.search(r"\b(?:детские сады|детский сад|садик|школа)\s+в\s+([А-ЯЁ][а-яё-]{4,})", text, re.IGNORECASE)
    if match:
        name = match.group(1).strip(" .,;")
        _add_unique(result, f"микрорайон {name}")
        _add_unique(result, name)

    match = re.search(r"\b(?:школа|детский сад|садик)\s+(?:в\s+)?(?:селе|село|с\.|с\s+)\s*([А-ЯЁ][а-яё-]{4,})", text, re.IGNORECASE)
    if match:
        _add_unique(result, f"село {match.group(1)}")

    match = re.search(r"\b(?:селе|село|с\.|с\s+)\s*([А-ЯЁ][а-яё-]{4,})", text, re.IGNORECASE)
    if match:
        locality = match.group(1).strip(" .,;")
        district_match = re.search(r"\b(?:мкр\.?|микрорайон)\s*([А-ЯЁ][а-яё-]{4,})", text, re.IGNORECASE)
        if district_match:
            district = district_match.group(1)
            _add_unique(result, f"село {locality}, микрорайон {district}")
            _add_unique(result, f"микрорайон {district}, село {locality}")
        _add_unique(result, f"село {locality}")
        if locality.endswith("ов"):
            _add_unique(result, f"село {locality}о")
        if locality.endswith("ан"):
            _add_unique(result, f"село {locality}ы")

    match = re.search(r"\b(?:пгт|пос\.|пос\s+|поселок)\s*([А-ЯЁ][а-яё-]{4,})(?:\s+ул\.?\s+([А-ЯЁ][а-яё-]{4,}))?", text, re.IGNORECASE)
    if match:
        locality = match.group(1)
        street = match.group(2)
        if street:
            _add_unique(result, f"поселок {locality}, улица {street}")
        _add_unique(result, f"поселок {locality}")

    if "северо" in low and "енисейск" in low:
        _add_unique(result, "Северо-Енисейский")
        _add_unique(result, "городской поселок Северо-Енисейский")

    capital = region_capital(region)
    if region and capital:
        case_tokens = important_tokens(text)
        comment_low = norm_match(comment_text)
        for token in case_tokens:
            if (
                f"микрорайон {token}" in comment_low
                or f"жилой район {token}" in comment_low
                or f"жилого района {token}" in comment_low
            ):
                _add_unique(result, f"{capital}, микрорайон {text}")
    return result


def _comment_query_variants(comment_text: str, *, case_name: str) -> list[str]:
    result: list[str] = []
    for match in re.finditer(
        r"(?:по\s+адресу[:;]?\s*)?"
        r"(?P<place>(?:село|с\.|пгт|пос\.|поселок|деревня)\s*[А-ЯЁ][а-яё-]{3,})"
        r"[^.\n]{0,80}?"
        r"(?P<street>(?:ул\.?|улица)\s*[А-ЯЁ][а-яё-]{3,}(?:\s+[А-ЯЁ][а-яё-]{3,}){0,2})"
        r"[, ]+(?:дом|д\.?)?\s*(?P<house>\d+[А-Яа-яA-Za-z]?)",
        comment_text,
        re.IGNORECASE,
    ):
        _add_unique(result, f"{match.group('place')}, {match.group('street')}, {match.group('house')}")
    for match in re.finditer(
        r"(?P<street>(?:ул\.?|улица)\s*[А-ЯЁ][а-яё-]{3,}(?:\s+[А-ЯЁ][а-яё-]{3,}){0,2})"
        r"[, ]+(?:дом|д\.?)?\s*(?P<house>\d+[А-Яа-яA-Za-z]?)",
        comment_text,
        re.IGNORECASE,
    ):
        street_text = norm_match(match.group("street"))
        if any(bad in street_text.split() for bad in {"живу", "больше", "минус", "против", "напротив", "к"}):
            continue
        _add_unique(result, f"{match.group('street')}, {match.group('house')}")
    if re.search(r"\bроддом\b", norm_match(case_name)):
        match = re.search(r"\bна\s+([А-ЯЁ][а-яё-]{4,})", comment_text, re.IGNORECASE)
        if match:
            _add_unique(result, f"{case_name}, улица {match.group(1)}")
    if "перенсон" in norm_match(comment_text):
        _add_unique(result, "улица Перенсона")
    return result[:8]


def _extract_context_parts(*values: Any) -> list[str]:
    blob = "\n".join(str(value or "") for value in values if value)
    if not blob:
        return []
    patterns = [
        r"\b(?:г\.?|город(?:е|а|у|ом)?)\s*([А-ЯЁ][а-яё-]{3,})",
        r"\b([А-ЯЁ][а-яё-]+ского\s+муниципального\s+округа)",
        r"\b([А-ЯЁ][а-яё-]+ский\s+муниципальный\s+округ)",
        r"\b([А-ЯЁ][а-яё-]+ского\s+района)",
        r"\b([А-ЯЁ][а-яё-]+ский\s+район)",
        r"\b([А-ЯЁ][а-яё-]+ской\s+области)",
        r"\b([А-ЯЁ][а-яё-]+ская\s+область)",
        r"\b([А-ЯЁ][а-яё-]+ского\s+края)",
        r"\b([А-ЯЁ][а-яё-]+ский\s+край)",
        r"\b(Республика\s+[А-ЯЁ][а-яё-]+)",
    ]
    blocked = {"россии", "москве", "подмосковье", "беларуси"}
    result: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, blob):
            text = match.group(1).strip(" .,;:!?()[]{}«»")
            key = norm_match(text)
            if not key or key in seen or key in blocked:
                continue
            seen.add(key)
            result.append(text)
            if len(result) >= 6:
                return result
    return result


def _extract_near_district_localities(comment_text: str, case_name: str) -> list[str]:
    if not any(marker in norm_match(case_name) for marker in ("район", "р н", "округ")):
        return []
    result: list[str] = []
    case_tokens = important_tokens(case_name)
    for match in re.finditer(
        r"\b(?:в|во)\s+([А-ЯЁ][а-яё-]{4,})\s+([А-ЯЁа-яё-]+)\s+(?:р-н|район|округ)",
        comment_text,
        re.IGNORECASE,
    ):
        locality = match.group(1).strip(" .,;")
        tail_tokens = important_tokens(match.group(2))
        if tail_tokens and not tail_tokens.intersection(case_tokens):
            continue
        _add_unique(result, locality)
    return result


def build_geocode_queries(ctx: LocationContext) -> tuple[str, list[str]]:
    region = infer_effective_region(ctx)
    case_name = norm(ctx.case_name)
    variants: list[str] = []

    for query in _address_hierarchy_queries(ctx):
        _add_unique(variants, _query(region, query) if region else query)

    if _is_region_only_case(case_name):
        capital = region_capital(case_name)
        if capital:
            _add_unique(variants, f"{case_name}, {capital}")

    for query in _comment_query_variants(ctx.comment_text, case_name=case_name):
        _add_unique(variants, _query(region, query) if region else query)
    for rewritten in _case_rewrite_variants(case_name, region=region, comment_text=ctx.comment_text):
        _add_unique(variants, _query(region, rewritten) if region else rewritten)
    for locality in _extract_near_district_localities(ctx.comment_text, case_name):
        _add_unique(variants, _query(region, f"{locality}, {case_name}") if region else f"{locality}, {case_name}")

    owner_variant = _owner_street_variant(case_name)
    if region and owner_variant:
        _add_unique(variants, _query(region, owner_variant))

    for context in _extract_context_parts(ctx.comment_text, ctx.source_title):
        context_low = norm_match(context)
        if region and any(marker in context_low for marker in ("края", "области", "республика")):
            continue
        if region and important_tokens(context).issubset(important_tokens(region)):
            continue
        if context_low and context_low not in norm_match(case_name):
            _add_unique(variants, _query(region, f"{context}, {case_name}") if region else f"{context}, {case_name}")

    public_city = locality_from_public(ctx.public_name, ctx.source_title)
    if region and public_city and not _has_explicit_locality(case_name):
        # Город паблика — раньше столицы: «улица Мира» из паблика Железногорска
        # должна искаться в Железногорске, а не по всему краю.
        _add_unique(variants, f"{region}, {public_city}, {case_name}")

    capital = region_capital(region)
    if region and capital and _looks_like_street_or_house(case_name) and not _has_explicit_locality(case_name):
        _add_unique(variants, f"{region}, {capital}, {case_name}")
    if region and capital and not _has_explicit_locality(case_name):
        case_tokens = important_tokens(case_name)
        comment_low = norm_match(ctx.comment_text)
        if case_tokens and any(
            f"район {token}" in comment_low
            or f"района {token}" in comment_low
            or f"жилой район {token}" in comment_low
            or f"жилого района {token}" in comment_low
            for token in case_tokens
        ):
            _add_unique(variants, f"{region}, {capital}, {case_name}")

    _add_unique(variants, _query(region, case_name) if region else case_name)
    return region, variants[:10]


def _token_stem(token: str) -> str:
    if len(token) <= 5:
        return token
    for suffix in ("ского", "ской", "ский", "ская", "ское", "ово", "ево", "ого", "ому", "ами", "ями", "ая", "ий", "ый", "ой", "ом", "ах", "ях", "ов", "ев", "ым", "им", "ы", "а", "е", "о"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 5:
            return token[: -len(suffix)]
    return token[:8]


def _tokens_loosely_subset(expected: set[str], provider: set[str]) -> bool:
    if not expected:
        return False
    provider_stems = {_token_stem(token) for token in provider}
    for token in expected:
        stem = _token_stem(token)
        if not any(stem == p or stem.startswith(p) or p.startswith(stem) for p in provider_stems):
            return False
    return True


def _geo_matches_region(expected_region: str, point: GeoPoint) -> bool:
    # Регион паблика известен не всегда. Без него проверка пропускала ответ
    # откуда угодно, и «Трасса 42, 2» находилась в Туркестане.
    if not expected_region:
        from backend.app.config import settings

        expected_region = str(getattr(settings, "GEO_DEFAULT_REGION", "") or "")
    if not expected_region:
        return True
    blob = norm_match(" ".join([point.region, point.municipality, point.locality, point.provider_text, point.provider_description]))
    return norm_match(expected_region) in blob


def _is_obvious_non_address(ctx: LocationContext, expected_region: str, point: GeoPoint) -> bool:
    raw = norm_match(ctx.case_name)
    if raw in {"промзона", "промышленная зона"}:
        return True
    if not expected_region and raw in {"п лично", "лично", "макс"}:
        return True
    if expected_region:
        capital = norm_match(region_capital(expected_region))
        if raw in {capital, f"город {capital}", f"г {capital}"}:
            return True
    if not expected_region and any(marker in raw for marker in ("школа искусств", "детская школа искусств")):
        return True
    if _looks_like_city_only_case(ctx.case_name) and norm_match(point.provider_kind) not in {"locality", "province", "area"}:
        return True
    return False


def _looks_like_city_only_case(value: Any) -> bool:
    low = norm_match(value)
    tokens = low.split()
    if not tokens:
        return False
    if any(marker in tokens for marker in {"ул", "улица", "дом", "проспект", "проезд", "переулок"}):
        return False
    return any(marker in tokens for marker in {"г", "город", "село", "поселок", "пгт", "деревня", "станица"})


def _stems_overlap(left: set[str], right: set[str]) -> bool:
    # Стемминг грубый («Норильск» / «Норильске» → разные стемы), поэтому
    # сравниваем по префиксу, как в _tokens_loosely_subset.
    return any(
        _stems_match(a, b)
        for a in left
        for b in right
    )


# Слова-типы административных единиц. В названии населённого пункта они шум:
# «городской округ ЗАТО Железногорск» отличается от «города Дивногорска» именно
# именем, а не словом «город».
_ADMIN_WORDS = frozenset({
    "городской", "городского", "городском", "городская", "городские", "города",
    "округ", "округа", "округе", "округу", "зато",
    "муниципальный", "муниципального", "муниципальное", "муниципальном",
    "район", "района", "районе", "поселение", "поселения",
    "сельский", "сельское", "сельского", "территория", "территории",
    "край", "края", "область", "области", "республика", "республики",
})


def _locality_tokens(value: Any) -> set[str]:
    return {token for token in important_tokens(value) if token not in _ADMIN_WORDS}


def _point_locality_mentioned(point: GeoPoint, comment_text: str) -> bool:
    point_stems = {
        _locality_stem(token)
        for token in _locality_tokens(" ".join([point.municipality, point.locality]))
    }
    comment_stems = {_locality_stem(token) for token in _locality_tokens(comment_text)}
    return _stems_overlap(point_stems, comment_stems)


def _point_matches_locality(point: GeoPoint, locality: str) -> bool:
    stems = {_locality_stem(token) for token in _locality_tokens(
        " ".join([point.municipality, point.locality, point.provider_text])
    )}
    return _stems_overlap({_locality_stem(locality)}, stems)


def _point_in_other_known_city(point: GeoPoint, public_city: str) -> bool:
    """Точка попала в другой город из справочника, а не в село рядом."""
    for token in _locality_tokens(" ".join([point.municipality, point.locality])):
        found = known_locality(token)
        if found and found != public_city:
            return True
    return False


def resolve_case_locality(ctx: LocationContext) -> str:
    """Населённый пункт кейса: сначала названный в нём самом, потом у площадки.

    Кейс важнее: «МБОУ СОШ 9 г. Лесосибирска» относится к Лесосибирску, даже
    если пишет о нём краевой паблик.
    """

    for token in str(ctx.case_name or "").replace(".", " ").replace(",", " ").split():
        found = known_locality(token)
        if found:
            return found
    return locality_from_public(ctx.public_name, ctx.source_title)


def point_contradicts_public_city(ctx: LocationContext, point: GeoPoint) -> bool:
    """Точка уехала в другой известный город, чем тот, о котором пишет площадка.

    Кейс-улица без города, но город площадки известен: «улица Мира» от
    администрации Ачинского округа не должна вставать в Зеленогорске. Сёла и
    посёлки вокруг не отсекаем — паблик райцентра обычно пишет и про свой район.
    Если житель сам назвал город точки в комментарии, возражений нет.

    Решение опирается только на координаты и населённый пункт ответа, поэтому
    годится и для перепроверки старых записей кэша, где часть служебных полей
    геокодера могла не сохраниться.
    """

    public_city = locality_from_public(ctx.public_name, ctx.source_title)
    return bool(
        public_city
        and not _has_explicit_locality(ctx.case_name)
        and not _point_matches_locality(point, public_city)
        and _point_in_other_known_city(point, public_city)
        and not _point_locality_mentioned(point, ctx.comment_text)
    )


def point_in_expected_region(expected_region: str, point: GeoPoint) -> bool:
    """Только проверка региона — для повторного разбора записей кэша.

    Полная приёмка там не годится: она отбраковывает и точку из соседнего
    города, а на чтении это уводило улицу в другой населённый пункт.
    """

    return _geo_matches_region(expected_region, point)


def accept_geocode_result(ctx: LocationContext, query: str, expected_region: str, point: GeoPoint) -> bool:
    if not _geo_matches_region(expected_region, point):
        return False
    if _is_obvious_non_address(ctx, expected_region, point):
        return False

    # Кейс-улица без города, но город паблика известен: не принимаем точку из
    # ДРУГОГО города по запросу без локалитета — иначе «улица Мира» уезжает в
    # первый попавшийся город края. Сёла и посёлки вокруг не отсекаем: паблик
    # райцентра обычно пишет и про свой район.
    if point_contradicts_public_city(ctx, point):
        return False

    if point.source != "yandex" or point.precision != "other":
        return True

    provider_kind = norm_match(point.provider_kind)
    if provider_kind not in {"locality", "district", "area", "province"}:
        return False

    provider_tokens = important_tokens(
        " ".join(
            [
                point.provider_name,
                point.provider_text,
                point.provider_description,
                point.locality,
                point.municipality,
                point.region,
            ]
        )
    )
    expected_region_tokens = important_tokens(expected_region)
    candidate_tokens = important_tokens(ctx.case_name) | important_tokens(query)
    candidate_tokens -= expected_region_tokens
    if provider_kind in {"area", "province"} and not any(
        marker in norm_match(ctx.case_name) for marker in ("район", "округ", "область", "край", "республика")
    ):
        return False
    return _tokens_loosely_subset(candidate_tokens, provider_tokens)
