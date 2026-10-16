from backend.db.posts import Post
from backend.modules.patterns.errors import ModuleError


class ModuleContextBuilder:
    """Собирает текстовый контекст для генерации конфигурации модуля."""

    def __init__(
        self,
        *,
        context_limit: int = 6000,
        post_limit: int = 800,
    ):
        self.context_limit = context_limit
        self.post_limit = post_limit

    def build(self, posts: list[Post]) -> str:
        chunks = [chunk for post in posts if (chunk := self._post_chunk(post))]
        if not chunks:
            raise ModuleError(
                "Нет опубликованных постов для генерации configuration"
            )
        return "\n\n---\n\n".join(chunks)[: self.context_limit]

    def _post_chunk(self, post: Post) -> str | None:
        title = (post.title or "").strip()
        text = (post.text_final or "").strip()

        if not title and not text:
            return None

        return f"Заголовок: {title}\nТекст: {text}"[: self.post_limit]
