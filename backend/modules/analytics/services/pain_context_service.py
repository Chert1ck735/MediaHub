"""Сервис подготовки context болей из snapshot payload."""

from backend.db import AnalysisSnapshot, Pain
from backend.modules.analytics.services.case_filter_service import filter_subproblem_items_cases, \
    compute_case_blacklist_from_snapshot
from backend.modules.analytics.services.pain_context_filter_service import PainContextFilterService
from backend.modules.analytics.services.payload_helpers import build_pain_context
from backend.modules.analytics.utils.case_extractor import case_location_key


class PainContextService:
    """Строит, фильтрует и нормализует context pain'а."""

    def __init__(self) -> None:
        self._filter = PainContextFilterService()

    def build(self, snapshot: AnalysisSnapshot | None, pain: Pain) -> dict:
        """Возвращает context из snapshot или пустой context."""

        if snapshot is None:
            return self.empty_context()
        return build_pain_context(snapshot, pain)

    def filter_by_comment_ids(self, context: dict, valid_cids: set[str]) -> dict:
        """Оставляет в context только элементы выбранной площадки."""

        return self._filter.filter_by_comment_ids(context, valid_cids)

    def merge_cases(self, context: dict, key_map: dict) -> dict:
        """Складывает адреса подпроблем по общему ключу места."""

        return self._filter.merge_cases(context, key_map)

    def clean_subproblem_items(self, snapshot: AnalysisSnapshot | None, context: dict) -> list[dict]:
        """Фильтрует псевдо-кейсы внутри subproblem_items."""

        blacklist = compute_case_blacklist_from_snapshot(snapshot) if snapshot else set()
        return filter_subproblem_items_cases(
            list(context.get("subproblem_items", []) or []),
            blacklist,
        )

    def collect_top_cases(self, cleaned_subitems: list[dict]) -> list[dict]:
        """Собирает top_cases с дедупом по нормализованной локации."""

        merged: dict[str, dict] = {}
        for subitem in cleaned_subitems:
            for case in subitem.get("cases", []) or []:
                title = (case.get("title") or "").strip()
                if not title:
                    continue
                key = case_location_key(title) or title.lower()
                mentions = int(case.get("mentions_count", 0) or 0)
                if key in merged:
                    merged[key]["mentions_count"] += mentions
                else:
                    merged[key] = {"title": title, "mentions_count": mentions}
        return sorted(merged.values(), key=lambda item: item["mentions_count"], reverse=True)

    @staticmethod
    def empty_context() -> dict:
        """Пустой context для pain без snapshot."""

        return {
            "comment_examples": [],
            "subproblems": [],
            "subproblem_items": [],
            "sentiment_counts": {},
            "message_type_counts": {},
            "request_count": 0,
            "complaint_count": 0,
            "communication_strategy": None,
            "subcategory": None,
            "publications_count": 0,
        }
