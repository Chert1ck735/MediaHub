from types import SimpleNamespace

from backend.modules.llm.providers.openai_compatible_client import OpenAICompatibleClient


class _FakeChatCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="готово"))],
            usage=None,
        )


def test_openai_compatible_disables_thinking_in_extra_body():
    completions = _FakeChatCompletions()
    client = OpenAICompatibleClient(
        model="test-model",
        base_url="http://example.test/v1",
        api_key="dummy",
        timeout=30,
        think=True,
    )
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
        close=lambda: None,
    )

    result = client.generate([{"role": "user", "content": "Ответь кратко"}])

    assert result == "готово"
    assert completions.kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
