from pathlib import Path

import numpy as np

from backend.modules.condition.interfaces import ConditionCalculator, PostRepository
from backend.modules.condition.models import ConditionResult, WINDOW
from backend.modules.condition.repositories.csv_post_repository import CsvPostRepository
from backend.modules.condition.services.condition_calculator import ErConditionCalculator


class ConditionService:
    """Оценивает состояние сообщества по вовлечённости постов."""

    def __init__(
        self,
        *,
        post_repository: PostRepository | None = None,
        calculator: ConditionCalculator | None = None,
    ):
        self.post_repository = post_repository or CsvPostRepository()
        self.calculator = calculator or ErConditionCalculator()

    def assess(self, path: Path, *, window: int = WINDOW) -> ConditionResult:
        posts = self.post_repository.list_posts(path)
        if not posts:
            return ConditionResult("NORMAL", 0.0, 0.0, 0.0, 0)

        crisis_threshold, rise_threshold = self.calculator.compute_thresholds(
            posts,
            window=window,
        )
        last = posts[-window:]
        avg_er = float(np.mean([post.er_post for post in last]))
        state = self.calculator.detect_state(
            avg_er,
            crisis_threshold,
            rise_threshold,
        )
        return ConditionResult(
            state,
            avg_er,
            crisis_threshold,
            rise_threshold,
            len(last),
        )
