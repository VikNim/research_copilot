"""Chat completions via Databricks Foundation Model APIs — Claude Haiku 4.5,
called through the OpenAI-compatible surface Databricks exposes.

Same caveat as embeddings.py: UNVERIFIED against a real workspace. Confirm the
endpoint path/response shape once Lakebase/Databricks infra actually exists.
"""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from research_copilot.config import Settings, get_settings


class LLMNotConfigured(RuntimeError):
    pass


def _client(settings: Settings) -> OpenAI:
    if not settings.has_fm_api:
        raise LLMNotConfigured("Set DATABRICKS_FM_BASE_URL and DATABRICKS_FM_TOKEN to enable the agent.")
    return OpenAI(base_url=settings.fm_api_base_url, api_key=settings.fm_api_token)


def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> Any:
    settings = settings or get_settings()
    client = _client(settings)
    kwargs: dict[str, Any] = {"model": settings.llm_model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
    return client.chat.completions.create(**kwargs)
