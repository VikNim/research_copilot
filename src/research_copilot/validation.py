"""Search input validation for Screen 1 — rejects blank, whitespace-only,
digits-only, and symbols-only queries before they ever reach the agent."""

from __future__ import annotations

import re

_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)  # at least one actual letter
MAX_QUERY_LENGTH = 300


def validate_search_query(query: str | None) -> tuple[bool, str | None]:
    if query is None:
        return False, "Enter a topic to search for."

    stripped = query.strip()
    if not stripped:
        return False, "Enter a topic to search for."

    if len(stripped) > MAX_QUERY_LENGTH:
        return False, f"Keep it under {MAX_QUERY_LENGTH} characters."

    if not _HAS_LETTER.search(stripped):
        return False, "Enter a topic in words — numbers or symbols alone aren't enough to search on."

    return True, None
