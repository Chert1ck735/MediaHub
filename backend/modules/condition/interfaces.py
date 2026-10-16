from pathlib import Path
from typing import Protocol

from backend.modules.condition.models import ConditionResult, Post


class PostRepository(Protocol):
    def list_posts(self, path: Path) -> list[Post]:
        ...


class ConditionCalculator(Protocol):
    def compute_thresholds(
        self,
        posts: list[Post],
        *,
        window: int,
    ) -> tuple[float, float]:
        ...

    def detect_state(
        self,
        avg_er: float,
        crisis_threshold: float,
        rise_threshold: float,
    ) -> str:
        ...


class ConditionAssessor(Protocol):
    def assess(self, path: Path, *, window: int) -> ConditionResult:
        ...
