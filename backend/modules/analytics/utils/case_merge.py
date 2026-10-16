"""Единые правила склейки адресов: одно место — одна строка.

Списков адресов в интерфейсе и отчёте три: карточка боли, подпроблема и
отчёт. Раньше у каждого была своя склейка, и одна улица показывалась то одной
строкой, то тремя. Правила лежат здесь, чтобы расходиться было негде.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from backend.modules.analytics.utils.address_normalizer import (
    address_display_title,
    is_address_like,
)
from backend.modules.analytics.utils.case_extractor import case_location_key

# Одноимённые улицы в разных сёлах — обычное дело: «ул. Комсомольская» есть
# в четырёх местах края. Склейка по названию не должна их путать.
SAME_PLACE_DEGREES = 0.1

_NON_WORD_RE = re.compile(r"[^a-zа-я0-9]+")

# Слова, которые сами по себе места не называют. «Дорога между домами
# Киренского 116 и 118» после обрезки пояснения превращается в «Дорога», и по
# такому остатку разные дороги города складывались в одну строку.
_GENERIC_STEMS = frozenset({
    "дорог", "дорожк", "перекрест", "остановк", "мост", "двор", "тротуар",
    "проезд", "площад", "участок", "поворот", "съезд", "подъезд", "переход",
    "трасс", "развязк", "лестниц", "переул", "набережн", "объезд",
})


def display_key(title: str) -> str:
    """Подпись без регистра, ё и знаков — чтобы поймать одинаковые на вид."""

    return " ".join(_NON_WORD_RE.sub(" ", title.lower().replace("ё", "е")).split())


def near(first: tuple[float, float] | None, second: tuple[float, float] | None) -> bool:
    """Точки достаточно близки, чтобы считать их одним местом."""

    if first is None or second is None:
        return True
    return (
        abs(first[0] - second[0]) <= SAME_PLACE_DEGREES
        and abs(first[1] - second[1]) <= SAME_PLACE_DEGREES
    )


# Номер дома вместе с буквой: «13Б» и «13 Б» — это один и тот же дом, а «13А»
# — уже соседний. Через отдельные слова букву теряло, и дома слипались.
_HOUSE_NUMBER_RE = re.compile(
    r"(?<![а-яa-z0-9])(\d{1,4})\s*([а-яa-z])?(?![а-яa-z0-9])", re.IGNORECASE
)


def title_parts(title: str) -> tuple[frozenset, frozenset]:
    """Слова названия и номера домов по отдельности."""

    houses = {
        f"{number}{letter.lower()}" if letter else number
        for number, letter in _HOUSE_NUMBER_RE.findall(title.replace("ё", "е"))
    }
    stems = {
        token for token in case_location_key(title).split() if not token[:1].isdigit()
    }
    return frozenset(stems), frozenset(houses)


# Пропущенный пробел внутри названия: строчная перед прописной или число,
# слипшееся со словом.
_GLUED_RE = re.compile(r"[а-яё][А-ЯЁ]|\d[А-ЯЁа-яё]{3,}")
_STREET_WORD_RE = re.compile(
    r"^(?:ул|улиц\w*|просп\w*|пр-?кт|пр-?т|переул\w*|пер|шоссе|наб|набережн\w*|"
    r"бульвар|проезд|тракт|мкр|микрорайон)(?![а-яёa-z])",
    re.IGNORECASE,
)


def label_rank(display: str, place_stems: frozenset) -> tuple:
    """Насколько подпись годится как основная для места.

    Из нескольких написаний одного адреса раньше бралось самое короткое, и
    в списке оказывались «2 Школы, Минусинск» вместо «школа №2, Минусинск» и
    «Красноярск, Карбышева 10а» вместо «Карбышева, 10А, Красноярск». Сначала
    смотрим на вид подписи, и только потом на длину.
    """

    parts = [part.strip() for part in display.split(",") if part.strip()]
    head = parts[0] if parts else display
    starts_with_number = head[:1].isdigit()
    # Город в начале — это перевёрнутый адрес, а не заголовок. Пустой набор
    # слов сюда не относится: «2 Микрорайон» состоит из числа и типа места.
    head_stems = set(case_location_key(head).split())
    place_first = bool(place_stems) and bool(head_stems) and head_stems <= place_stems
    # Слипшиеся слова: «ЯрыгинскаяНабережная», «2Микрорайон». Такой вариант
    # короче на пробел, и по одной длине выигрывал у правильного.
    glued = bool(_GLUED_RE.search(head))
    # «ул. Нагорная» понятнее, чем «Нагорную»: тип улицы заодно вытягивает
    # название в именительный падеж.
    no_street_word = not _STREET_WORD_RE.search(head)
    return (place_first, glued, no_street_word, starts_with_number, len(display), display)


class CaseKeys:
    """Считает общий ключ для всех написаний одного места."""

    def __init__(self) -> None:
        self._by_display: dict[str, tuple[str, tuple[float, float] | None]] = {}
        self._about: dict[str, tuple[frozenset, frozenset, tuple | None]] = {}

    def add(self, title: str, geo: Mapping[str, object] | None) -> tuple[str, str] | None:
        """Ключ и подпись для написания. ``None`` — если это не адрес."""

        if not geo or not is_address_like(title, geo):
            return None

        # Геокодер сводит написания к одному объекту и возвращает его имя —
        # это самый надёжный признак, что место одно. Но имя не уникально:
        # «Нагорная улица» есть и в Солонцах, и в Мазульском, и по одному
        # имени эти улицы слипались в одну. Поэтому к имени добавляется
        # грубая клетка примерно в десяток километров.
        display = address_display_title(title, geo)
        stems, houses = title_parts(display)

        canonical = display_key(str(geo.get("provider_name") or ""))
        lat, lon = geo.get("lat"), geo.get("lon")
        point = (float(lat), float(lon)) if lat is not None and lon is not None else None
        # Дом входит в ключ: геокодер на «Чкалова 13А» и «Чкалова 13Б»
        # возвращает одну улицу, и без номера соседние дома слипались.
        at_house = "#" + ",".join(sorted(houses)) if houses else ""
        if canonical and point is not None:
            key = f"{canonical}@{round(point[0], 1)},{round(point[1], 1)}{at_house}"
        elif canonical:
            key = f"{canonical}{at_house}"
        elif point is not None:
            key = f"{round(point[0], 3)},{round(point[1], 3)}{at_house}"
        else:
            key = (case_location_key(title) or title.lower()) + at_house
        place = " ".join(
            part
            for part in (str(geo.get("locality") or ""), str(geo.get("municipality") or ""))
            if part
        )
        place_stems = frozenset(case_location_key(place).split())
        # Собственное название места: без города и без общих слов. «Дорога
        # между домами Киренского 116 и 118» после обрезки пояснения даёт
        # подпись «Дорога, Красноярск» — такая же, как у соседней дороги.
        core = stems - place_stems - _GENERIC_STEMS

        # Канонического имени может не быть, а координаты у двух написаний
        # расходятся дальше квартала. Тогда ловим по видимой подписи — но
        # только если в ней есть собственное название.
        shown = display_key(display) if core else ""
        if shown:
            seen = self._by_display.get(shown)
            if seen is not None and near(seen[1], point):
                key = seen[0]
            elif seen is None:
                self._by_display[shown] = (key, point)

        self._about.setdefault(key, (stems, houses, point, place_stems))
        return key, display

    def remap(self) -> dict[str, str]:
        """Сводит написания одного места к общему ключу.

        Правил два. Первое: наборы слов совпадают — «Нагорная, посёлок
        Солонцы» и «Солонцы Нагорная, посёлок Солонцы». Второе: одно название
        отличается от другого только упомянутым населённым пунктом —
        «ул. Нагорная» и «Нагорная, посёлок Солонцы». Оба требуют, чтобы дом
        не различался и точки были рядом.

        Второе правило намеренно узкое. Если разрешить любое вхождение слов,
        короткое «Красноярск» становится магнитом и стягивает к себе все
        адреса города, а «Перекрёсток Чкалова и 30 Лет Победы» связывает две
        улицы в одну. Поэтому лишними могут быть только слова территории, и
        цепочек нет: написание уходит к одному месту и мостом не работает.
        """

        groups: dict[frozenset, list[tuple[str, tuple]]] = {}
        for key, about in sorted(self._about.items()):
            stems = about[0]
            # Без собственного названия сводить нечего: «Дорога между домами
            # Киренского 116 и 118» после обрезки пояснения даёт «Дорога,
            # Красноярск», и по такому остатку разные дороги города сходились
            # в одну строку. Название города при проверке не считается.
            core = stems - about[3] - _GENERIC_STEMS
            if not stems or not core:
                continue
            groups.setdefault(stems, []).append((key, about))

        def same_place(first: tuple, second: tuple) -> bool:
            """Дом не различается и точки рядом."""

            return first[1] == second[1] and near(first[2], second[2])

        remap: dict[str, str] = {}
        leaders: dict[frozenset, list[tuple[str, tuple]]] = {}
        for stems, members in groups.items():
            chosen: list[tuple[str, tuple]] = []
            for key, about in members:
                found = next((one for one in chosen if same_place(one[1], about)), None)
                if found is None:
                    chosen.append((key, about))
                else:
                    remap[key] = found[0]
            leaders[stems] = chosen

        for stems, members in leaders.items():
            for key, about in members:
                # Лишние слова должны быть названием территории этого адреса.
                target = next(
                    (
                        leader[0]
                        for other in sorted(leaders, key=lambda one: (len(one), sorted(one)))
                        if other < stems and (stems - other) <= about[3]
                        for leader in leaders[other]
                        if same_place(leader[1], about)
                    ),
                    None,
                )
                if target is not None:
                    remap[key] = target

        # Написание могло сначала уйти к своему представителю, а тот — к более
        # короткому названию. Дорешиваем ссылки, иначе одна улица остаётся
        # двумя строками.
        def final(key: str) -> str:
            seen = {key}
            while key in remap and remap[key] not in seen:
                key = remap[key]
                seen.add(key)
            return key

        return {key: final(key) for key in remap}
