"""Embeddings via Databricks Foundation Model APIs (OpenAI-compatible endpoint).

UNVERIFIED end-to-end — there's no Databricks workspace/FM API endpoint wired up
yet (see project memory: infra starts from zero). The client shape below matches
Databricks' documented OpenAI-compatible surface; confirm the exact endpoint path
and response shape once real credentials exist.

v1 scope: embeds abstracts, notes, and learning-goal text as single vectors —
no chunking. A whole paper's full text (if v1.1 adds it) would need chunking
first; short text like this doesn't.
"""

from __future__ import annotations

from openai import OpenAI

from research_copilot.config import Settings, get_settings


class EmbeddingsNotConfigured(RuntimeError):
    pass


def _client(settings: Settings) -> OpenAI:
    if not settings.has_fm_api:
        raise EmbeddingsNotConfigured(
            "Set DATABRICKS_FM_BASE_URL and DATABRICKS_FM_TOKEN to enable embeddings."
        )
    return OpenAI(base_url=settings.fm_api_base_url, api_key=settings.fm_api_token)


def embed_texts(texts: list[str], settings: Settings | None = None) -> list[list[float]]:
    """Batch-embeds a list of strings. Empty/whitespace-only entries are sent through
    as-is — callers are expected to filter those out before calling (see validation.py
    for the equivalent guard on user-facing search input)."""
    if not texts:
        return []
    settings = settings or get_settings()
    client = _client(settings)
    response = client.embeddings.create(model=settings.embedding_model, input=texts)
    return [item.embedding for item in response.data]


def embed_text(text: str, settings: Settings | None = None) -> list[float]:
    return embed_texts([text], settings=settings)[0]
