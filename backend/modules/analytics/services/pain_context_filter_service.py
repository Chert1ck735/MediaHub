"""Фильтрация snapshot-контекста боли для UI."""

import re
from typing import Any

from backend.modules.analytics.utils.address_normalizer import (
    address_display_title,
    is_address_like,
    trim_address_tail,
)
from backend.modules.analytics.utils.severity_rules import severity_from_share

def _display_key(title: str) -> str:
    """Подпись без регистра, ё и знаков — для поиска одинаковых на вид."""

    text = re.sub(r"[^a-zа-я0-9]+", " ", title.lower().replace("ё", "е"))
    return " ".join(text.split())


class PainContextFilterService:
    """Фильтрует контекст боли под площадку/период."""

    def filter_by_comment_ids(
        self,
        context: dict[str, Any],
        valid_cids: set[str],
    ) -> dict[str, Any]:
        """Возвращает копию context только с comment_id из valid_cids."""

        def _cid(item: Any) -> str | None:
            if isinstance(item, dict):
                value = item.get("comment_id")
                return str(value) if value else None
            return None

        new_subitems: list[dict[str, Any]] = []
        for subproblem in context.get("subproblem_items") or []:
            new_cases: list[dict[str, Any]] = []
            for case in subproblem.get("cases") or []:
                examples = [
                    example
                    for example in case.get("comment_examples") or []
                    if _cid(example) and _cid(example) in valid_cids
                ]
                if examples:
                    new_cases.append(
                        {
                            **case,
                            "comment_examples": examples,
                            "mentions_count": len(examples),
                        }
                    )

            subproblem_examples = [
                example
                for example in subproblem.get("comment_examples") or []
                if _cid(example) and _cid(example) in valid_cids
            ]

            if new_cases or subproblem_examples:
                new_subitems.append(
                    self._recount_subproblem(
                        subproblem,
                        new_cases,
                        subproblem_examples,
                        _cid,
                    )
                )

        new_comment_examples = [
            example
            for example in context.get("comment_examples") or []
            if _cid(example) and _cid(example) in valid_cids
        ]

        return {
            **context,
            "subproblem_items": new_subitems,
            "subproblems": [
                item["title"]
                for item in new_subitems
                if item.get("title")
            ],
            "comment_examples": new_comment_examples,
        }

    def merge_cases(
        self,
        context: dict[str, Any],
        key_map: dict[str, tuple[str, str]],
    ) -> dict[str, Any]:
        """Складывает адреса подпроблем, если это одно и то же место.

        Списки адресов внутри подпроблем приходят из снапшота как есть: одна
        улица лежит там несколькими написаниями и показывается несколько раз.
        ``key_map`` приносит общий ключ для написаний одного места.
        """

        def _merged(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for case in cases:
                raw = str(case.get("raw_title") or case.get("title") or "").strip()
                # Название территории — не адрес, в списке адресов ему не место.
                if not is_address_like(raw):
                    continue
                key, display = key_map.get(raw, ("", ""))
                if not key:
                    # Живая выборка это написание не знает: пары «место —
                    # координаты» нет. Тогда складываем по самой подписи —
                    # одинаковые на вид строки в одной подпроблеме это одно
                    # место, показывать их дважды незачем.
                    display = address_display_title(trim_address_tail(raw))
                    key = f"={_display_key(display)}"
                existing = out.get(key)
                if existing is None:
                    out[key] = {**case, "title": display or case.get("title"), "raw_title": raw}
                    continue

                existing["mentions_count"] = int(existing.get("mentions_count", 0) or 0) + int(
                    case.get("mentions_count", 0) or 0
                )
                seen = {
                    str(example.get("comment_id"))
                    for example in existing.get("comment_examples") or []
                }
                for example in case.get("comment_examples") or []:
                    cid = str(example.get("comment_id"))
                    if cid not in seen:
                        seen.add(cid)
                        existing.setdefault("comment_examples", []).append(example)
                existing["comment_examples"] = (existing.get("comment_examples") or [])[:5]
                if len(raw) < len(existing.get("raw_title") or ""):
                    existing["raw_title"] = raw

            return sorted(
                out.values(),
                key=lambda item: int(item.get("mentions_count", 0) or 0),
                reverse=True,
            )

        subitems = []
        for subproblem in context.get("subproblem_items") or []:
            cases = list(subproblem.get("cases") or [])
            subitems.append({**subproblem, "cases": _merged(cases)} if cases else subproblem)

        return {**context, "subproblem_items": subitems}

    def severity_from_share(self, mentions: int, total: int) -> str:
        """Severity среза — через канон severity_rules.severity_from_share (с потолком)."""
        return severity_from_share(mentions, total)

    def _recount_subproblem(
        self,
        subproblem: dict[str, Any],
        cases: list[dict[str, Any]],
        examples: list[dict[str, Any]],
        cid_getter,
    ) -> dict[str, Any]:
        """Пересчитывает согласованные счётчики подпроблемы."""
        seen_cids: set[str] = set()
        pool: list[dict[str, Any]] = []

        for example in examples + [
            item
            for case in cases
            for item in case.get("comment_examples", [])
        ]:
            cid = cid_getter(example)
            if cid and cid not in seen_cids:
                seen_cids.add(cid)
                pool.append(example)

        sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}
        message_type_counts = {
            "complaint": 0,
            "request": 0,
            "gratitude": 0,
            "offtopic": 0,
            "sarcasm": 0,
        }

        for example in pool:
            sentiment = str(example.get("sentiment") or "")
            if sentiment in sentiment_counts:
                sentiment_counts[sentiment] += 1

            message_type = str(example.get("message_type") or "")
            if message_type in message_type_counts:
                message_type_counts[message_type] += 1

        return {
            **subproblem,
            "cases": cases,
            "comment_examples": examples,
            "mentions_count": len(pool)
            or sum(case.get("mentions_count", 0) for case in cases),
            "complaint_count": (
                message_type_counts["complaint"]
                + message_type_counts["sarcasm"]
            ),
            "request_count": message_type_counts["request"],
            "sentiment_counts": sentiment_counts,
            "message_type_counts": message_type_counts,
        }
