"""Chat completions via Databricks Foundation Model APIs — Claude Haiku 4.5,
called through the OpenAI-compatible surface Databricks exposes.

UNVERIFIED against a real workspace — confirm the endpoint path/response shape
once a login session + FM API access actually exist. See databricks_auth.py for
how the bearer token is obtained (OAuth via CLI profile, no PAT required).
"""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from research_copilot.config import Settings, get_settings
from research_copilot.databricks_auth import FMAuthNotConfigured, resolve_bearer_token


class LLMNotConfigured(RuntimeError):
    pass


STYLE_DIRECTIVE = "Never use em dashes (—) in your writing. Use a comma, period, or parentheses instead."


def _with_style_directive(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Applied centrally here rather than at each call site (Workspace.py's
    summarizer, agent.py's tool loop, study_buddy.py's explanations) so the
    style rule can't be missed on a new one."""
    if messages and messages[0].get("role") == "system":
        first = {**messages[0], "content": f"{messages[0]['content']}\n\n{STYLE_DIRECTIVE}"}
        return [first, *messages[1:]]
    return [{"role": "system", "content": STYLE_DIRECTIVE}, *messages]


def _client(settings: Settings) -> OpenAI:
    if not settings.has_fm_api:
        raise LLMNotConfigured(
            "Set DATABRICKS_FM_BASE_URL, and either DATABRICKS_FM_TOKEN or DATABRICKS_PROFILE, to enable the agent."
        )
    try:
        token = resolve_bearer_token(settings)
    except FMAuthNotConfigured as exc:
        raise LLMNotConfigured(str(exc)) from exc
    return OpenAI(base_url=settings.fm_api_base_url, api_key=token)


def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> Any:
    settings = settings or get_settings()
    client = _client(settings)
    kwargs: dict[str, Any] = {"model": settings.llm_model, "messages": _with_style_directive(messages)}
    if tools:
        kwargs["tools"] = tools
    return client.chat.completions.create(**kwargs)
