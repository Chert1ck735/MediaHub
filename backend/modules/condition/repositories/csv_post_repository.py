import csv
from pathlib import Path

from backend.modules.condition.models import Post


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class CsvPostRepository:
    """Читает метрики постов из CSV с разделителем «точка с запятой»."""

    def list_posts(self, path: Path) -> list[Post]:
        if not path.exists():
            return []

        with path.open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file, delimiter=";")
            posts = [
                Post(
                    date=row.get("date", ""),
                    likes=_to_int(row.get("likes")),
                    reposts=_to_int(row.get("reposts")),
                    comments=_to_int(row.get("comments")),
                    views=_to_int(row.get("views")),
                )
                for row in reader
            ]

        posts.sort(key=lambda post: post.date)
        return posts
