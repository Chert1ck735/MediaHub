from backend.modules.llm.clients import LLMError
from backend.modules.llm.schemas import CommentAnalysisResponse
from backend.modules.llm.services.comment_analysis_service import CommentAnalysisService


async def analyze_comment(
    text: str,
    model: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    repeat_penalty: float | None = None,
    system_prompt_template: str | None = None,
) -> CommentAnalysisResponse:
    """Фасад совместимости для вызовов анализа комментариев."""

    return await CommentAnalysisService().analyze(
        text,
        model=model,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        repeat_penalty=repeat_penalty,
        system_prompt_template=system_prompt_template
    )


__all__ = ["analyze_comment", "LLMError"]
