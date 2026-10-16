from __future__ import annotations

from backend.modules.llm.prompt_loader import load_prompt, render_prompt


NAME = "digital_krasnoyarsk"
TITLE = load_prompt("profiles/digital_krasnoyarsk/title.md")

EXAMPLE_OUTPUT = load_prompt("profiles/digital_krasnoyarsk/example_output.md")

SYSTEM = render_prompt(
    "profiles/digital_krasnoyarsk/system.md",
    title=TITLE,
    example_output=EXAMPLE_OUTPUT,
)

