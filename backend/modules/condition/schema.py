from typing import Optional

from pydantic import BaseModel, Field


class AssessRequest(BaseModel):
    csv_path: Optional[str] = Field(
        default=None,
        description="Путь к CSV с постами. По умолчанию — posts.csv",
    )
    window: int = Field(default=5, ge=2, description="Размер окна для rolling-средних")


class AssessResponse(BaseModel):
    state: str
    avg_er: float
    crisis_threshold: float
    rise_threshold: float
    sample_size: int
