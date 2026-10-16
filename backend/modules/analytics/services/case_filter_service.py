"""Фильтрация «псевдо-кейсов» в выводе аналитики.

Бывает, что LLM кладёт в поле ``case`` название обобщённой темы
(«Переселение с Крайнего Севера», «Тарифы и начисления ЖКХ») вместо
конкретного адреса. Такие значения нужно прятать в API-ответах, иначе
они засоряют ``top_cases`` и пересекаются между разными болями.

Здесь — две связанные функции:
  * ``compute_case_blacklist_from_snapshot`` — строит чёрный список
    кросс-pain дубликатов по структурированному snapshot'у;
  * ``filter_subproblem_items_cases`` — применяет чёрный список и
    эвристику валидности к подпроблемам в ответе API.
"""

from __future__ import annotations

from backend.db.analysis_snapshots import AnalysisSnapshot
from backend.modules.analytics.schemas import StructuredPainAnalyticsPayload
from backend.modules.analytics.utils.case_extractor import is_valid_case_title


def compute_case_blacklist_from_snapshot(snapshot: AnalysisSnapshot) -> set[str]:
    """Названия кейсов, которые встретились в ≥2 разных болях одного snapshot'a.

    Это сигнал, что LLM скопировала общую тему вместо конкретного
    адресного кейса — такие записи в API-ответе не нужны.
    """

    if not snapshot or not snapshot.raw_payload:
        return set()
    try:
        payload = StructuredPainAnalyticsPayload.model_validate(snapshot.raw_payload)
    except Exception:
        return set()
    case_to_pains: dict[str, set[str]] = {}
    for pain_item in payload.pains:
        for sp in (pain_item.subproblem_items or []):
            for case in (sp.cases or []):
                title = (case.title or "").strip().lower()
                if not title:
                    continue
                case_to_pains.setdefault(title, set()).add(pain_item.title)
    return {key for key, names in case_to_pains.items() if len(names) >= 2}


def filter_subproblem_items_cases(
    subproblem_items: list[dict] | list,
    blacklist: set[str],
) -> list[dict]:
    """Применяет blacklist + heuristic к ``cases`` внутри ``subproblem_items``.

    Возвращает копию списка с очищенными ``cases``; оригинал не мутирует.
    Используется и в ``/pains/{id}``, и в ``/pains`` (list), чтобы
    фильтрация была одинаковой в обоих местах.
    """

    cleaned: list[dict] = []
    for sp in subproblem_items:
        if hasattr(sp, "model_dump"):
            sp_d = sp.model_dump(mode="json")
        elif isinstance(sp, dict):
            sp_d = dict(sp)
        else:
            sp_d = dict(sp)
        cases = sp_d.get("cases") or []
        filtered_cases: list[dict] = []
        seen: set[str] = set()
        for case in cases:
            if hasattr(case, "model_dump"):
                case_d = case.model_dump(mode="json")
            elif isinstance(case, dict):
                case_d = dict(case)
            else:
                case_d = dict(case)
            title = (case_d.get("title") or "").strip()
            key = title.lower()
            if not key or key in seen:
                continue
            if key in blacklist:
                continue
            if not is_valid_case_title(title):
                continue
            seen.add(key)
            filtered_cases.append(case_d)
        sp_d["cases"] = filtered_cases
        cleaned.append(sp_d)
    return cleaned
