import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.modules import Module
from backend.db.users import User
from backend.modules.patterns.configuration_generator import ModuleConfigurationGenerator
from backend.modules.patterns.errors import ModuleError
from backend.modules.patterns.interfaces import (
    ModuleConfigurationProvider,
    ModuleReaderWriter,
)
from backend.modules.patterns.repositories.module_repository import ModuleRepository
from backend.modules.patterns.services.module_context_builder import ModuleContextBuilder


def _require_org(user: User) -> uuid.UUID:
    if not user.organization_id:
        raise ModuleError("У пользователя не задана организация")
    return user.organization_id


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ModuleService:
    """Выполняет сценарии списка модулей и их создания или изменения."""

    def __init__(
        self,
        db: AsyncSession | None = None,
        *,
        repository: ModuleReaderWriter | None = None,
        configuration_generator: ModuleConfigurationProvider | None = None,
        context_builder: ModuleContextBuilder | None = None,
    ):
        if repository is None:
            if db is None:
                raise ValueError("ModuleService requires db or repository")
            repository = ModuleRepository(db)

        self.repository = repository
        self.configuration_generator = (
            configuration_generator or ModuleConfigurationGenerator()
        )
        self.context_builder = context_builder or ModuleContextBuilder()

    async def list_modules(self, user: User) -> list[Module]:
        organization_id = _require_org(user)
        return await self.repository.list_by_organization(organization_id)

    async def create_or_update_module(
        self,
        user: User,
        *,
        name: str,
        goal: str | None,
        description: str | None,
    ) -> tuple[Module, bool]:
        organization_id = _require_org(user)
        module_name = name.strip()
        if not module_name:
            raise ModuleError("Название модуля не может быть пустым")

        public = await self.repository.get_public_by_name(organization_id, module_name)
        if not public:
            raise ModuleError("Паблик не найден. Название должно совпадать 1:1")

        context_text = await self._load_publication_context(public.id)
        configuration = self.configuration_generator.generate(context_text)

        module = await self.repository.get_by_public_id(public.id)
        created = module is None
        if module is None:
            module = Module(public_id=public.id)
            await self.repository.add(module)

        module.name = module_name
        module.goal = _clean(goal)
        module.description = _clean(description)
        module.configuration = configuration

        await self.repository.commit()
        await self.repository.refresh(module)
        return module, created

    async def _load_publication_context(self, public_id: uuid.UUID) -> str:
        posts = await self.repository.list_recent_published_posts(public_id)
        return self.context_builder.build(posts)
