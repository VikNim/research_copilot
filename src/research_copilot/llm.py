"""Chat completions — the primary chat proxy (CHAT_PROXY_BASE_URL/CHAT_PROXY_API_KEY),
falling back to a second proxy (CHAT_FALLBACK_PROXY_BASE_URL/CHAT_FALLBACK_PROXY_API_KEY/
CHAT_FALLBACK_MODEL) on an auth/quota error from the primary, falling back to Databricks
Foundation Model APIs if neither proxy is configured at all. Embeddings (embeddings.py)
always use Databricks regardless of which of these is active — neither proxy has an
embeddings endpoint of its own. See databricks_auth.py for how the Databricks bearer
token is obtained (OAuth via CLI profile or a service principal).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import openai
from openai import OpenAI

from research_copilot.config import Settings, get_settings
from research_copilot.databricks_auth import FMAuthNotConfigured, resolve_bearer_token

logger = logging.getLogger(__name__)


class LLMNotConfigured(RuntimeError):
    pass


# The primary proxy rejects every request, including a plain models.list(), without
# this header ("Missing session identifier" — discovered live, not documented
# anywhere we were given). One id for the life of this process is enough; the proxy
# just needs *a* session identifier, not one tied to a specific Streamlit user.
# Not sent to the fallback proxy — a different vendor, no reason to assume it wants
# the same header, and nothing so far has shown it does.
_PROXY_SESSION_ID = str(uuid.uuid4())

# Trigger for falling over to the fallback proxy: the primary chat proxy reports
# quota/credential problems as 401 (AuthenticationError) — confirmed live via
# "Monthly token limit exceeded" — RateLimitError (429) is included too since
# that's the more conventional status code for the same kind of problem and costs
# nothing to also handle.
_FAILOVER_ERRORS = (openai.AuthenticationError, openai.RateLimitError)


STYLE_DIRECTIVE = "Never use em dashes (—) in your writing. Use a comma, period, or parentheses instead."


def _with_style_directive(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Applied centrally here rather than at each call site (Workspace.py's
    summarizer, agent.py's tool loop, study_buddy.py's explanations) so the
    style rule can't be missed on a new one."""
    if messages and messages[0].get("role") == "system":
        first = {**messages[0], "content": f"{messages[0]['content']}\n\n{STYLE_DIRECTIVE}"}
        return [first, *messages[1:]]
    return [{"role": "system", "content": STYLE_DIRECTIVE}, *messages]


def _primary_client_and_model(settings: Settings) -> tuple[OpenAI, str]:
    if settings.has_chat_proxy:
        client = OpenAI(
            base_url=settings.chat_proxy_base_url,
            api_key=settings.chat_proxy_api_key,
            default_headers={"x-session-id": _PROXY_SESSION_ID},
        )
        return client, settings.llm_model
    if not settings.has_fm_api:
        raise LLMNotConfigured(
            "Set CHAT_PROXY_BASE_URL/CHAT_PROXY_API_KEY, or DATABRICKS_FM_BASE_URL plus "
            "DATABRICKS_FM_TOKEN/DATABRICKS_PROFILE, to enable the agent."
        )
    try:
        token = resolve_bearer_token(settings)
    except FMAuthNotConfigured as exc:
        raise LLMNotConfigured(str(exc)) from exc
    return OpenAI(base_url=settings.fm_api_base_url, api_key=token), settings.llm_model


def _fallback_client_and_model(settings: Settings) -> tuple[OpenAI, str] | None:
    if not settings.has_chat_fallback_proxy:
        return None
    client = OpenAI(base_url=settings.chat_fallback_proxy_base_url, api_key=settings.chat_fallback_proxy_api_key)
    return client, settings.chat_fallback_model


def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> Any:
    settings = settings or get_settings()
    kwargs: dict[str, Any] = {"messages": _with_style_directive(messages)}
    if tools:
        kwargs["tools"] = tools

    client, model = _primary_client_and_model(settings)
    try:
        return client.chat.completions.create(model=model, **kwargs)
    except _FAILOVER_ERRORS as primary_exc:
        fallback = _fallback_client_and_model(settings)
        if fallback is None:
            raise
        logger.warning("Primary chat provider failed (%s) — retrying with the fallback proxy.", primary_exc)
        fallback_client, fallback_model = fallback
        return fallback_client.chat.completions.create(model=fallback_model, **kwargs)
