import numpy as np

from backend.modules.condition.models import Post


class ErConditionCalculator:
    """Считает пороги ER и переводит текущий ER в состояние сообщества."""

    def compute_thresholds(
        self,
        posts: list[Post],
        *,
        window: int,
    ) -> tuple[float, float]:
        er = [post.er_post for post in posts]
        if len(er) < window:
            return 0.0, 0.0

        rolling = [
            float(np.mean(er[index - window + 1 : index + 1]))
            for index in range(window - 1, len(er))
        ]
        if not rolling:
            return 0.0, 0.0

        return float(np.percentile(rolling, 25)), float(np.percentile(rolling, 75))

    def detect_state(
        self,
        avg_er: float,
        crisis_threshold: float,
        rise_threshold: float,
    ) -> str:
        if avg_er < crisis_threshold:
            return "CRISIS"
        if avg_er > rise_threshold:
            return "RISE"
        return "NORMAL"
