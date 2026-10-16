"""Красноярские муниципалитеты и эвристика привязки пабликов.

Список зеркалит frontend/src/app/krasnoyarskMunicipalities.ts: это один
прикладной справочник, только на сервере он ещё используется для валидации и
автоподбора.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from backend.app.config import PROJECT_ROOT

KRASNOYARSK_KRAI_NAME = "Красноярский край"

_ADMIN_STOPWORDS = {
    "муниципальный",
    "муниципального",
    "муниципальное",
    "муниципальном",
    "образование",
    "городской",
    "городского",
    "городском",
    "округ",
    "округа",
    "округе",
    "район",
    "района",
    "районе",
    "р-н",
    "зато",
    "пгт",
    "поселок",
    "посёлок",
    "город",
    "города",
    "г",
    "п",
    "край",
    "края",
    "красноярский",
    "красноярского",
}

_RAW_MUNICIPALITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Дивногорск", ("Дивногорск",)),
    ("Красноярск", ("Красноярск",)),
    ("Норильск", ("Норильск",)),
    ("Железногорск (ЗАТО)", ("Железногорск",)),
    ("Зеленогорск (ЗАТО)", ("Зеленогорск",)),
    ("Солнечный (ЗАТО)", ("Солнечный",)),
    ("Абанский округ", ("Абанский",)),
    ("Ачинский округ", ("Ачинский", "Ачинск")),
    (
        "Балахтинско-Новоселовский округ",
        ("Балахтинско-Новоселовский", "Балахтинский", "Новоселовский"),
    ),
    ("Бирилюсский округ", ("Бирилюсский",)),
    ("Боготольский округ", ("Боготольский", "Боготол")),
    ("Богучанский округ", ("Богучанский",)),
    (
        "Большемуртинско-Сухобузимский округ",
        ("Большемуртинско-Сухобузимский", "Большемуртинский", "Сухобузимский"),
    ),
    (
        "Дзержинско-Тасеевский округ",
        ("Дзержинско-Тасеевский", "Дзержинский", "Тасеевский"),
    ),
    ("Емельяновский округ", ("Емельяновский",)),
    ("Енисейский округ", ("Енисейский", "Енисейск", "Лесосибирск")),
    ("Ермаковский округ", ("Ермаковский",)),
    (
        "Идринско-Краснотуранский округ",
        ("Идринско-Краснотуранский", "Идринский", "Краснотуранский"),
    ),
    (
        "Иланско-Нижнеингашский округ",
        ("Иланско-Нижнеингашский", "Иланский", "Нижнеингашский"),
    ),
    (
        "Ирбейско-Саянский округ",
        ("Ирбейско-Саянский", "Ирбейский", "Саянский"),
    ),
    (
        "Казачинско-Пировский округ",
        ("Казачинско-Пировский", "Казачинский", "Пировский"),
    ),
    ("Канский округ", ("Канский", "Канск")),
    ("Каратузский округ", ("Каратузский",)),
    ("Кежемский округ", ("Кежемский",)),
    ("Козульский округ", ("Козульский",)),
    ("Курагинский округ", ("Курагинский",)),
    # Короткие названия городов перечислены с падежами явно: правила словоформ
    # рассчитаны на «-ск» и «-ский», а «Уяра» под них не подходит.
    ("Манско-Уярский округ", ("Манско-Уярский", "Манский", "Уярский", "Уяр", "Уяра")),
    ("Минусинский округ", ("Минусинский", "Минусинск")),
    ("Мотыгинский округ", ("Мотыгинский",)),
    ("Назаровский округ", ("Назаровский", "Назарово")),
    ("Рыбинский округ", ("Рыбинский", "Бородино", "Заозерный")),
    ("Северо-Енисейский округ", ("Северо-Енисейский",)),
    ("Сосновоборский округ", ("Сосновоборский", "Сосновоборск")),
    ("Таймырский Долгано-Ненецкий округ", ("Таймырский Долгано-Ненецкий", "Дудинка")),
    ("Туруханский округ", ("Туруханский",)),
    ("Ужурский округ", ("Ужурский",)),
    ("Шарыповский округ", ("Шарыповский", "Шарыпово")),
    ("Шушенский округ", ("Шушенский",)),
    ("Эвенкийский округ", ("Эвенкийский",)),
)


@dataclass(frozen=True)
class MunicipalityOption:
    label: str
    keys: tuple[str, ...]


def _normalize_text(value: str | None) -> str:
    return (
        (value or "")
        .lower()
        .replace("ё", "е")
        .replace("—", "-")
        .replace("–", "-")
    )


def _tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-zа-я0-9]+(?:-[a-zа-я0-9]+)*", _normalize_text(value))


def normalize_municipality(value: str | None) -> str:
    return " ".join(
        token
        for token in _tokens(value)
        if token and token not in _ADMIN_STOPWORDS
    ).strip()


def _word_forms(source: str) -> set[str]:
    source = _normalize_text(source).strip()
    forms = {source}
    if source.endswith("ск"):
        forms.update({f"{source}а", f"{source}е", f"{source}ом"})
        # Городские советы называются прилагательным: «Дивногорский городской
        # Совет депутатов», «Бородинский», «Норильский».
        forms.update({f"{source}ий", f"{source}ого", f"{source}ому", f"{source}им"})
    if source.endswith("о"):
        forms.update({source[:-1], f"{source[:-1]}е"})
    if source.endswith(("ский", "цкий")):
        stem = source[:-2]
        forms.update(
            {
                source,
                f"{stem}ого",
                f"{stem}ому",
                f"{stem}ом",
                f"{stem}им",
                f"{stem}ая",
                f"{stem}ое",
                f"{stem}ие",
                f"{stem}их",
            }
        )
    return {form for form in forms if form}


def _source_aliases(source: str) -> tuple[str, ...]:
    aliases: set[str] = set()
    normalized = normalize_municipality(source)
    if normalized:
        aliases.add(normalized)
    for part in re.split(r"[\s-]+", _normalize_text(source)):
        if not part or part in _ADMIN_STOPWORDS:
            continue
        aliases.update(_word_forms(part))
    return tuple(sorted(aliases, key=len, reverse=True))


KRASNOYARSK_MUNICIPALITIES: tuple[MunicipalityOption, ...] = tuple(
    sorted(
        (
            MunicipalityOption(
                label=label,
                keys=tuple(
                    sorted(
                        {
                            alias
                            for source in sources
                            for alias in _source_aliases(source)
                            if alias
                        },
                        key=len,
                        reverse=True,
                    )
                ),
            )
            for label, sources in _RAW_MUNICIPALITIES
        ),
        key=lambda item: item.label,
    )
)

_BY_NORMALIZED_LABEL = {
    normalize_municipality(option.label): option.label
    for option in KRASNOYARSK_MUNICIPALITIES
}


def canonical_municipality_name(value: str | None) -> str | None:
    normalized = normalize_municipality(value)
    if not normalized:
        return None
    return _BY_NORMALIZED_LABEL.get(normalized)


def is_krasnoyarsk_region_name(value: str | None) -> bool:
    return _normalize_text(value).strip() == _normalize_text(KRASNOYARSK_KRAI_NAME)


def mentions_krasnoyarsk_krai(*texts: str | None) -> bool:
    haystack = " ".join(_normalize_text(text) for text in texts if text)
    return bool(
        re.search(r"\bкрасноярск(?:ий|ого|ом|ому|им)\s+кра(?:й|я|е|ю|ем)\b", haystack)
        or re.search(r"\bкрасноярь[ея]\b", haystack)
    )


_RE_KRAI = re.compile(r"\bкрасноярск(?:ий|ого|ом|ому|им)\s+кра(?:й|я|е|ю|ем)\b")


# Сокращения территорий из названий органов: «Управление образования
# Администрации ТДНМР», «Финансовое управление Администрации БСМО», «Управление
# ЗАГС Таймыра». По самому названию округа такие не распознаются.
_ABBREVIATIONS: tuple[tuple[str, str], ...] = (
    ("тднмр", "Таймырский Долгано-Ненецкий округ"),
    ("таймыр", "Таймырский Долгано-Ненецкий округ"),
    ("таймыра", "Таймырский Долгано-Ненецкий округ"),
    ("эвенкии", "Эвенкийский округ"),
    ("эвенкия", "Эвенкийский округ"),
    ("эмр", "Эвенкийский округ"),
    ("бсмо", "Большемуртинско-Сухобузимский округ"),
    ("смо", "Сосновоборский округ"),
)
# «ЕМО» сюда не входит: так сокращают и Емельяновский, и Енисейский округ.
# Обе площадки с этим сокращением на проде — лесосибирские, то есть Енисейский.


def _municipality_by_abbreviation(haystack: str) -> str | None:
    for abbreviation, label in _ABBREVIATIONS:
        if _contains_alias(haystack, abbreviation):
            return label
    return None


def _contains_alias(haystack: str, alias: str) -> bool:
    pattern = r"(?<![a-zа-я0-9])" + re.escape(alias).replace(r"\ ", r"[\s-]+") + r"(?![a-zа-я0-9])"
    return re.search(pattern, haystack) is not None


def infer_krasnoyarsk_municipality(*texts: str | None) -> str | None:
    haystack = " ".join(_normalize_text(text) for text in texts if text)
    # «Красноярского края» — это регион, а не город. Иначе любой краевой орган
    # получал бы Красноярск: формы прилагательного у города и края совпадают.
    haystack = _RE_KRAI.sub(" ", haystack)
    if not haystack:
        return None

    scored: list[tuple[int, int, str]] = []
    for option in KRASNOYARSK_MUNICIPALITIES:
        score = 0
        longest = 0
        for alias in option.keys:
            if _contains_alias(haystack, alias):
                score += 1
                longest = max(longest, len(alias))
        if score:
            if _contains_alias(haystack, normalize_municipality(option.label)):
                score += 2
            scored.append((score, longest, option.label))

    if not scored:
        return (
            _municipality_by_abbreviation(haystack)
            or _municipality_by_settlement(haystack)
        )
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][:2] == scored[1][:2]:
        # Ничья между округом и составным соседом ложная: «Енисейского округа»
        # подходит и Енисейскому, и Северо-Енисейскому. Раз отличающая часть
        # («Северо») в тексте не названа, речь про короткий.
        short, long = sorted((scored[0][2], scored[1][2]), key=len)
        if long.endswith(short) or short in long:
            return short
        return None
    return scored[0][2]


_SETTLEMENTS: dict[str, str] | None = None


def _settlement_map() -> dict[str, str]:
    """Населённый пункт → округ, собранный из открытых данных Енисей-ГИС.

    Названия округов сами по себе покрывают только райцентры и города. Паблик
    вроде «Администрация городского поселения Диксон» территории не получал:
    Диксон — посёлок Таймырского округа, но в списке муниципалитетов его нет.
    """
    global _SETTLEMENTS
    if _SETTLEMENTS is None:
        path = PROJECT_ROOT / "data" / "settlement_municipality.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        _SETTLEMENTS = {_normalize_text(name).strip(): value for name, value in raw.items()}
    return _SETTLEMENTS


# Формы названия посёлка, встречающиеся в названиях площадок: падежи и
# прилагательное — «Диксонский городской Совет депутатов».
#
# Голой основы здесь нет намеренно. У «Верещагино» она даёт «верещагин» —
# обычную фамилию, и любой Сергей Верещагин получал Туруханский округ. Пользы
# от неё нет: там, где основа совпадает с названием, оно и так лежит в
# справочнике точным ключом.
_SETTLEMENT_SUFFIXES = (
    "а", "е", "ом",
    "ский", "ского", "ском", "ская", "ское",
)

_SETTLEMENT_FORMS: dict[str, str] | None = None

# После шипящих и «к», «г», «х» родительный падеж на «-и», иначе на «-ы»:
# «Дудинка» → «Дудинки», но «Мурта» → «Мурты».
_GENITIVE_SOFT = "кгхжчшщ"


def _genitive_one(word: str, *, adjective: bool) -> str | None:
    """Родительный падеж одного слова названия."""
    if adjective and word.endswith("ая"):
        return f"{word[:-2]}ой"
    if word.endswith(("ый", "ий")):
        return f"{word[:-2]}ого"
    if word.endswith("а"):
        return word[:-1] + ("и" if len(word) > 1 and word[-2] in _GENITIVE_SOFT else "ы")
    if word.endswith("я"):
        return f"{word[:-1]}и"
    if word.endswith("о"):
        return f"{word[:-1]}а"
    if word.endswith("ь"):
        return f"{word[:-1]}я"
    if word[-1:].isalpha() and word[-1] not in "аеёиоуыэюя":
        return f"{word}а"
    return None


def _genitive_forms(name: str) -> tuple[str, ...]:
    """Родительный падеж названия; у составных склоняются оба слова.

    «Большая Мурта» → «большой мурты»: первое слово согласуется как
    прилагательное, иначе получилось бы несуществующее «большая мурты».
    """
    words = name.split()
    if not words:
        return ()
    if len(words) == 1:
        form = _genitive_one(words[0], adjective=False)
        return (form,) if form and form != name else ()
    parts = [
        _genitive_one(word, adjective=index < len(words) - 1) or word
        for index, word in enumerate(words)
    ]
    form = " ".join(parts)
    return (form,) if form != name else ()


def _settlement_forms() -> dict[str, str]:
    """Все формы названий посёлков разом: поиск по токенам, а не перебором.

    Перебор восьмисот названий с регуляркой на каждое стоил секунды на площадку
    и делал автоподбор по всей организации неприемлемо долгим.
    """
    global _SETTLEMENT_FORMS
    if _SETTLEMENT_FORMS is not None:
        return _SETTLEMENT_FORMS

    settlements = _settlement_map()
    # Настоящие названия — первый сорт: производная форма одного посёлка не
    # должна перебивать имя другого. Совпали две производные из разных
    # округов — форму выбрасываем совсем: угаданная территория хуже пустой.
    forms: dict[str, str] = dict(settlements)
    derived: dict[str, str] = {}
    ambiguous: set[str] = set()

    def add(key: str, municipality: str) -> None:
        if key in settlements:
            return
        known = derived.get(key)
        if known is None:
            derived[key] = municipality
        elif known != municipality:
            ambiguous.add(key)

    for name, municipality in settlements.items():
        # «Администрация Дудинки», «Новости Абана» — в названиях площадок
        # посёлок чаще всего стоит именно в родительном падеже.
        for word in _genitive_forms(name):
            add(word, municipality)
        # Короткие названия в прилагательные не превращаем: «Тура» плюс «ский»
        # даёт слишком много ложных совпадений.
        if len(name) < 5:
            continue
        # Ключ уже прилагательное («покатеевского» из названия сельсовета):
        # добавляем остальные его формы, чтобы совпал и «Покатеевский».
        if name.endswith(("ского", "ский", "ском")):
            # «ского» — пять букв, «ский» и «ском» — четыре. Отрезав три,
            # получали «александровс» и дальше «александровсский».
            cut = 5 if name.endswith("ского") else 4
            stem = name[:-cut]
            for suffix in ("ский", "ского", "ском", "ская", "ское"):
                add(f"{stem}{suffix}", municipality)
            continue
        # «Дудинка» → «Дудинский», «Новопятницкое» → «Новопятницкий»,
        # «Толстихино» → «Толстихинский».
        stem = name[:-2] if name.endswith(("ка", "ко", "ое", "ая", "ый", "ий")) else name
        stem = stem[:-1] if stem.endswith(("о", "а", "ь")) else stem
        if stem.endswith(("ск", "цк")):
            # Название уже прилагательное («Агинское», «Новопятницкое»): к
            # основе идёт «-ий», иначе получается «новопятницкский».
            for suffix in ("", "ий", "ого", "ом", "ая", "ое", "им"):
                add(f"{stem}{suffix}", municipality)
        else:
            for suffix in _SETTLEMENT_SUFFIXES:
                add(f"{stem}{suffix}", municipality)
        # «Караул» → «Караульский»: прилагательное вставляет мягкий знак.
        if stem.endswith(("л", "н", "р")):
            for suffix in ("ьский", "ьского", "ьском"):
                add(f"{stem}{suffix}", municipality)

    for key, municipality in derived.items():
        if key not in ambiguous:
            forms[key] = municipality

    _SETTLEMENT_FORMS = forms
    return forms


def _municipality_by_settlement(haystack: str) -> str | None:
    """Округ по названию посёлка в тексте. Самое длинное совпадение выигрывает."""
    forms = _settlement_forms()
    tokens = haystack.split()
    best = ""
    found = None
    # Составные названия («Большая Мурта») проверяем вместе с одиночными.
    candidates = tokens + [
        f"{first} {second}" for first, second in zip(tokens, tokens[1:])
    ]
    for candidate in candidates:
        municipality = forms.get(candidate)
        if municipality and len(candidate) > len(best):
            best, found = candidate, municipality
    return found
