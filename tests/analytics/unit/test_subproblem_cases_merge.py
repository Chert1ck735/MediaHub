"""Список адресов в подпроблеме: строки из карточки «Качество дорог».

Одна улица приходила туда несколькими написаниями, а рядом лежали названия
территорий, которые адресом не являются.
"""
from backend.modules.analytics.services.pain_context_filter_service import (
    PainContextFilterService,
)


def _case(raw, mentions, cid):
    return {
        "title": raw,
        "raw_title": raw,
        "mentions_count": mentions,
        "comment_examples": [{"comment_id": cid, "text": f"комментарий {cid}"}],
    }


def _context(cases):
    return {"subproblem_items": [{"title": "Качество дорожного покрытия", "cases": cases}]}


def _cases_of(result):
    return result["subproblem_items"][0]["cases"]


def test_same_address_written_twice_becomes_one_row():
    context = _context([
        _case("Дубовицкого, посёлок Солонцы", 1, "c1"),
        _case("Дубовицкого, посёлок Солонцы", 1, "c2"),
    ])

    cases = _cases_of(PainContextFilterService().merge_cases(context, {}))

    assert len(cases) == 1
    assert cases[0]["mentions_count"] == 2
    # Оба комментария должны остаться: это разные люди.
    assert len(cases[0]["comment_examples"]) == 2


def test_territories_leave_the_address_list():
    context = _context([
        _case("Город Дивногорск", 1, "c1"),
        _case("ЗАТО Г. Железногорск", 1, "c2"),
        _case("Пгт. Березовка, городской посёлок Берёзовка", 1, "c3"),
        _case("ул. Внуковых", 1, "c4"),
    ])

    cases = _cases_of(PainContextFilterService().merge_cases(context, {}))

    assert [case["raw_title"] for case in cases] == ["ул. Внуковых"]


def test_tail_is_trimmed_in_the_card():
    context = _context([
        _case("ул. Нагорная В Солонцах У Складов Янта", 1, "c1"),
        _case("ул. Нагорная", 1, "c2"),
    ])

    cases = _cases_of(PainContextFilterService().merge_cases(context, {}))

    assert len(cases) == 1, "написания одной улицы остались разными строками"
    assert cases[0]["mentions_count"] == 2
