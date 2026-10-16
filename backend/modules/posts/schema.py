from pydantic import BaseModel, Field


class PublicationResponse(BaseModel):
    id: str
    post_id: str
    public_social_link_id: str
    platform: str
    public_title: str | None = None
    public_url: str | None = None
    status: str
    scheduled_at: str | None = None
    published_at: str | None = None
    external_post_id: str | None = None
    url: str | None = None
    error_message: str | None = None


class PostCreateRequest(BaseModel):
    title: str
    text_draft: str = ""
    text_generated: str = ""
    tone: str = ""
    vk_post_id: str | None = None
    strategy_id: str | None = None


class PostUpdateVkRequest(BaseModel):
    vk_post_id: str | None = None


class PostUpdateRequest(BaseModel):
    title: str | None = None
    text_draft: str | None = None
    text_generated: str | None = None
    tone: str | None = None
    strategy_id: str | None = None


class PostResponse(BaseModel):
    id: str
    title: str
    origin: str | None = None
    text_draft: str | None
    text_generated: str | None
    tone: str
    vk_post_id: str | None
    vk_wall_url: str | None
    strategy_id: str | None
    status: str
    scheduled_at: str | None = None
    published_at: str | None = None
    created_at: str
    publications: list[PublicationResponse] = Field(default_factory=list)


class PublicationCreateRequest(BaseModel):
    platform: str
    public_social_link_id: str | None = None
    scheduled_at: str | None = None
    status: str = "scheduled"
    external_post_id: str | None = None
    url: str | None = None
    published_at: str | None = None
    error_message: str | None = None


class PublicationUpdateRequest(BaseModel):
    platform: str | None = None
    public_social_link_id: str | None = None
    scheduled_at: str | None = None
    status: str | None = None
    external_post_id: str | None = None
    url: str | None = None
    published_at: str | None = None
    error_message: str | None = None
