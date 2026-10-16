import uuid
from typing import Any, Protocol

from backend.db.modules import Module
from backend.db.posts import Post
from backend.db.publics import Public


class ModuleReaderWriter(Protocol):
    async def get_public_by_name(
        self,
        organization_id: uuid.UUID,
        name: str,
    ) -> Public | None:
        ...

    async def list_recent_published_posts(
        self,
        public_id: uuid.UUID,
        limit: int = 30,
    ) -> list[Post]:
        ...

    async def get_by_public_id(self, public_id: uuid.UUID) -> Module | None:
        ...

    async def list_by_organization(self, organization_id: uuid.UUID) -> list[Module]:
        ...

    async def add(self, module: Module) -> Module:
        ...

    async def commit(self) -> None:
        ...

    async def refresh(self, module: Module) -> None:
        ...


class ModuleConfigurationProvider(Protocol):
    def generate(self, context_text: str) -> dict[str, Any]:
        ...


class LLMClient(Protocol):
    def generate(self, messages: list[dict]) -> str:
        ...

    def close(self) -> None:
        ...


class LLMClientFactory(Protocol):
    def __call__(self, **kwargs: Any) -> LLMClient:
        ...


class ConfigurationParser(Protocol):
    def parse(self, raw: str) -> dict[str, Any]:
        ...
