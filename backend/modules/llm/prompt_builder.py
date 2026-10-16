from types import ModuleType

from backend.modules.llm.prompt_loader import load_prompt
from backend.modules.llm.prompt_profiles import digital_krasnoyarsk


PROFILES: dict[str, ModuleType] = {digital_krasnoyarsk.NAME: digital_krasnoyarsk}
DEFAULT_PROFILE = digital_krasnoyarsk.NAME


class PromptBuilder:
    """Собирает системный промпт для текущего сценария генерации постов."""

    POST_TYPE_MODIFIERS = {
        name: load_prompt(f"builder/post_type_modifiers/{name}.md")
        for name in (
            "news",
            "event",
            "announcement",
            "congrats",
            "product",
            "achievement",
            "education",
            "initiative",
        )
    }

    def __init__(self, profile: ModuleType | str | None = None):
        profile = profile or DEFAULT_PROFILE
        if isinstance(profile, str):
            try:
                profile = PROFILES[profile]
            except KeyError as exc:
                raise ValueError(f"Неизвестный профиль prompt: {profile!r}") from exc
        self.profile = profile

    @property
    def system_prompt(self) -> str:
        return self.profile.SYSTEM

    def for_post_type(self, post_type: str | None) -> str:
        modifier = self.POST_TYPE_MODIFIERS.get((post_type or "").lower())
        return self.system_prompt if not modifier else f"{self.system_prompt}\n\n{modifier}"
