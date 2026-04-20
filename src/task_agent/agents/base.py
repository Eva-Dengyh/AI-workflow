"""BaseAgent：支持 Anthropic 格式和 OpenAI 兼容格式的双模式 API 封装"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from task_agent.settings import settings


def _load_prompt(name: str) -> str:
    prompt_dir = Path(__file__).parent.parent / "prompts"
    return (prompt_dir / f"{name}.txt").read_text(encoding="utf-8")


def _relay_headers() -> dict[str, str]:
    return {"User-Agent": f"claude-code/{settings.claude_code_version}"}


# ──────────────────────────────────────────────────────────────────────────────
# 客户端工厂
# ──────────────────────────────────────────────────────────────────────────────

def make_anthropic_client():
    """Anthropic 格式：适用于官方 API 或兼容 Anthropic 协议的中转站"""
    import httpx
    import anthropic

    def _fix_auth(request: httpx.Request) -> None:
        key = request.headers.get("x-api-key", "")
        if key:
            request.headers["authorization"] = f"Bearer {key}"
            del request.headers["x-api-key"]

    kwargs: dict = {
        "api_key": settings.anthropic_api_key,
        "base_url": settings.anthropic_base_url or None,
        "default_headers": _relay_headers(),
    }
    if settings.anthropic_base_url:
        kwargs["http_client"] = httpx.Client(event_hooks={"request": [_fix_auth]})
    return anthropic.Anthropic(**kwargs)


def make_openai_client():
    """OpenAI 兼容格式：适用于 /v1/chat/completions 格式的中转站"""
    from openai import OpenAI
    base = (settings.anthropic_base_url or "https://api.openai.com").rstrip("/")
    return OpenAI(
        api_key=settings.anthropic_api_key,
        base_url=f"{base}/v1",
        default_headers=_relay_headers(),
    )


# ──────────────────────────────────────────────────────────────────────────────
# BaseAgent
# ──────────────────────────────────────────────────────────────────────────────

class BaseAgent:
    def __init__(self, prompt_name: str) -> None:
        self.system_prompt = _load_prompt(prompt_name)
        self.model = settings.task_agent_model
        self._format = settings.task_agent_api_format  # "anthropic" | "openai"

        if self._format == "openai":
            self._client = make_openai_client()
        else:
            self._client = make_anthropic_client()

    @property
    def _system_block(self) -> list[dict]:
        return [{"type": "text", "text": self.system_prompt}]

    # ── 单次调用 ──────────────────────────────────────────────────────────────

    def call(self, messages: list[dict]) -> str:
        if self._format == "openai":
            return self._call_openai(messages)
        return self._call_anthropic(messages)

    def _call_anthropic(self, messages: list[dict]) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=8096,
            system=self._system_block,
            messages=messages,
        )
        return resp.content[0].text  # type: ignore[union-attr]

    def _call_openai(self, messages: list[dict]) -> str:
        full = [{"role": "system", "content": self.system_prompt}] + messages
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=8096,
            messages=full,
        )
        return resp.choices[0].message.content or ""

    # ── 流式调用 ──────────────────────────────────────────────────────────────

    def stream_call(self, messages: list[dict]) -> Iterator[str]:
        if self._format == "openai":
            yield from self._stream_openai(messages)
        else:
            yield from self._stream_anthropic(messages)

    def _stream_anthropic(self, messages: list[dict]) -> Iterator[str]:
        with self._client.messages.stream(
            model=self.model,
            max_tokens=8096,
            system=self._system_block,
            messages=messages,
        ) as stream:
            yield from stream.text_stream

    def _stream_openai(self, messages: list[dict]) -> Iterator[str]:
        full = [{"role": "system", "content": self.system_prompt}] + messages
        with self._client.chat.completions.stream(
            model=self.model,
            max_tokens=8096,
            messages=full,
        ) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
