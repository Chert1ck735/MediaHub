from backend.modules.analytics.constants import CATEGORY_ALIASES
from backend.modules.analytics.utils.text_normalize import match_alias


def test_keyword_in_text_still_matches():
    # прямое вхождение alias в текст — основной путь, не задет
    assert match_alias("ужасные дороги у нас", CATEGORY_ALIASES) == "Дороги и транспорт"


def test_truncated_llm_label_still_matches():
    # обратное вхождение для осмысленной метки (>=5 символов) сохраняется
    aliases = {"вывоз мусора": ("вывоз мусора",)}
    assert match_alias("вывоз мусо", aliases) == "вывоз мусора"


def test_short_noise_no_longer_matches_by_reverse():
    # короткий шум, который является подстрокой alias, больше не цепляет категорию
    aliases = {"Связь и цифровая инфраструктура": ("оптовол",)}
    assert match_alias("вол", aliases) is None


def test_short_exact_alias_still_matches():
    # точное короткое совпадение остаётся (alias в тексте)
    aliases = {"ЖКХ и городская среда": ("ук",)}
    assert match_alias("ук", aliases) == "ЖКХ и городская среда"
