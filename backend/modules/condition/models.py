from dataclasses import dataclass


WINDOW = 5


@dataclass
class Post:
    date: str
    likes: int
    reposts: int
    comments: int
    views: int

    @property
    def er_post(self) -> float:
        if self.views <= 0:
            return 0.0
        return (self.likes + self.reposts + self.comments) / self.views


@dataclass
class ConditionResult:
    state: str
    avg_er: float
    crisis_threshold: float
    rise_threshold: float
    sample_size: int
