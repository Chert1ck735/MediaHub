"""Compatibility facade for condition assessment."""

from pathlib import Path

from backend.modules.condition.models import ConditionResult, Post, WINDOW
from backend.modules.condition.repositories.csv_post_repository import CsvPostRepository
from backend.modules.condition.services.condition_calculator import ErConditionCalculator
from backend.modules.condition.services.condition_service import ConditionService


def load_posts(path: Path) -> list[Post]:
    return CsvPostRepository().list_posts(path)


def compute_thresholds(
    posts: list[Post],
    window: int = WINDOW,
) -> tuple[float, float]:
    return ErConditionCalculator().compute_thresholds(posts, window=window)


def detect_state(
    avg_er: float,
    crisis_threshold: float,
    rise_threshold: float,
) -> str:
    return ErConditionCalculator().detect_state(
        avg_er,
        crisis_threshold,
        rise_threshold,
    )


def assess(path: Path, window: int = WINDOW) -> ConditionResult:
    return ConditionService().assess(path, window=window)


__all__ = [
    "WINDOW",
    "Post",
    "ConditionResult",
    "load_posts",
    "compute_thresholds",
    "detect_state",
    "assess",
]
