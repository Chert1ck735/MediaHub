from backend.modules.llm.prompt_profiles import module_configuration


class ModuleConfigurationPromptBuilder:
    """Собирает сообщения для генерации конфигурации модуля."""

    def build_messages(self, context_text: str) -> list[dict]:
        return [
            {
                "role": "user",
                "content": (
                    module_configuration.SYSTEM
                    + "\n\n"
                    + module_configuration.get_module_generation_prompt(context_text)
                ),
            }
        ]
