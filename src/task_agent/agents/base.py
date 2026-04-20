"""BaseAgent：Claude API 调用封装，支持官方直连和第三方中转站"""

from pathlib import Path
from typing import Iterator

import anthropic

from task_agent.settings import settings


def _load_prompt(name: str) -> str:
    prompt_dir = Path(__file__).parent.parent / "prompts"
    return (prompt_dir / f"{name}.txt").read_text(encoding="utf-8")


class BaseAgent:
    def __init__(self, prompt_name: str) -> None:
        self.system_prompt = _load_prompt(prompt_name)
        self.model = settings.task_agent_model
        self.client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url or None,
        )

    def call(self, messages: list[dict]) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8096,
            system=self.system_prompt,
            messages=messages,
        )
        return response.content[0].text  # type: ignore[union-attr]

    def stream_call(self, messages: list[dict]) -> Iterator[str]:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=8096,
            system=self.system_prompt,
            messages=messages,
        ) as stream:
            yield from stream.text_stream
