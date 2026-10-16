"""DTO результатов автопарсера."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LinkAutoParseResult:
    """Итог обработки одной ссылки паблика за один проход автопарсера."""

    link_id: str
    network: str
    url: str
    public_id: str | None = None
    public_name: str | None = None

    # Дошли ли до проверки диффа (False — пропустили до неё: нет org-юзера,
    # ссылка не поддержана и т.п.).
    checked: bool = False
    # Нашла ли проверка неспаршенные комментарии за окно.
    had_diff: bool = False
    # Запускали ли реальный парс комментариев.
    parsed: bool = False

    posts_in_window: int = 0
    real_comments: int = 0          # сколько комментов у сети (по метрикам постов)
    stored_comments_before: int = 0  # сколько лежало у нас до парса
    unparsed_estimate: int = 0       # оценка «сколько не хватает» до парса
    comments_imported: int = 0       # реально сохранено новых на этом проходе

    skipped_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "link_id": self.link_id,
            "network": self.network,
            "url": self.url,
            "public_id": self.public_id,
            "public_name": self.public_name,
            "checked": self.checked,
            "had_diff": self.had_diff,
            "parsed": self.parsed,
            "posts_in_window": self.posts_in_window,
            "real_comments": self.real_comments,
            "stored_comments_before": self.stored_comments_before,
            "unparsed_estimate": self.unparsed_estimate,
            "comments_imported": self.comments_imported,
            "skipped_reason": self.skipped_reason,
            "error": self.error,
        }


@dataclass
class AutoParseRunResult:
    """Итог одного прохода автопарсера по набору ссылок."""

    started_at: str
    finished_at: str
    lookback_days: int
    links_total: int = 0
    links_checked: int = 0
    links_parsed: int = 0
    comments_imported: int = 0
    links: list[LinkAutoParseResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "lookback_days": self.lookback_days,
            "links_total": self.links_total,
            "links_checked": self.links_checked,
            "links_parsed": self.links_parsed,
            "comments_imported": self.comments_imported,
            "links": [link.to_dict() for link in self.links],
        }
