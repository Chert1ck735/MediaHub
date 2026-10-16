from typing import Any

from backend.modules.llm.interfaces import PublicModuleReader


class PublicModuleContextService:
    """Читает контекст модуля для сценариев генерации постов."""

    def __init__(self, module_reader: PublicModuleReader):
        self.module_reader = module_reader

    async def list_for_generation(
        self,
        *,
        public_social_link_id: str | None,
        organization_id: Any,
    ) -> list[dict[str, Any]]:
        return await self.module_reader.list_for_public_link(
            public_social_link_id=public_social_link_id,
            organization_id=organization_id,
        )

    async def get_generation_context(
        self,
        *,
        public_social_link_id: str,
        organization_id: Any,
    ) -> dict[str, Any]:
        return await self.module_reader.get_generation_context(
            public_social_link_id=public_social_link_id,
            organization_id=organization_id,
        )
