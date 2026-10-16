from typing import Optional

from pydantic import BaseModel, Field


class ReportGenerateRequest(BaseModel):
    platform: str = Field(..., description="Platform: vk or dzen")
    public_social_link_id: Optional[str] = Field(
        default=None,
        description="Optional source/public_social_link id for filtering one VK source",
    )
    municipality_name: Optional[str] = Field(
        default=None,
        description="Optional Krasnoyarsk municipality filter",
    )
    period: str = Field(
        default="week",
        description="Report period: week | month | year | all",
    )
    csv_path: Optional[str] = Field(
        default=None,
        description="Legacy CSV path. Kept only for backward compatibility.",
    )
    output_path: Optional[str] = Field(
        default=None,
        description="Optional PDF output path",
    )


class ReportGenerateResponse(BaseModel):
    platform: str
    output_path: str
    message: str = "Отчет успешно сгенерирован"


class ReportPreviewRequest(BaseModel):
    platform: str = Field(..., description="Platform: vk or dzen")
    public_social_link_id: Optional[str] = Field(
        default=None,
        description="Optional source/public_social_link id for filtering one VK source",
    )
    municipality_name: Optional[str] = Field(
        default=None,
        description="Optional Krasnoyarsk municipality filter",
    )
    period: str = Field(
        default="week",
        description="Report period: week | month | year | all",
    )
    csv_path: Optional[str] = Field(
        default=None,
        description="Legacy CSV path. Kept only for backward compatibility.",
    )


class ReportTimePoint(BaseModel):
    date: str
    views: int
    likes: Optional[int] = None
    comments: Optional[int] = None
    read_time_sec: Optional[int] = None


class ReportTopPost(BaseModel):
    date: Optional[str] = None
    text: str
    views: int
    likes: Optional[int] = None
    comments: Optional[int] = None
    url: Optional[str] = None


class ReportPreviewResponse(BaseModel):
    platform: str
    total_posts: int
    avg_views: float
    max_views: int
    avg_likes: Optional[float] = None
    max_likes: Optional[int] = None
    avg_comments: Optional[float] = None
    max_comments: Optional[int] = None
    group_members: Optional[int] = None
    channel: Optional[str] = None
    points: list[ReportTimePoint] = Field(default_factory=list)
    top_posts: list[ReportTopPost] = Field(default_factory=list)
    all_posts: list[ReportTopPost] = Field(default_factory=list)
    recommendations: str = ""
    # Окно пика активности аудитории — подсказка редактору, когда публиковать.
    recommended_post_window: Optional[str] = None
    # 7×24 матрица (dow × hour) с количеством комментариев — для heatmap.
    # heatmap[0] = воскресенье, heatmap[6] = суббота.
    activity_heatmap: Optional[list[list[int]]] = None
