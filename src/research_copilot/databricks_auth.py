"""Shared bearer-token resolution for calling Databricks Foundation Model APIs —
used by both llm.py and embeddings.py.

Prefers a static token (DATABRICKS_FM_TOKEN) if one's set, otherwise mints a fresh
OAuth token from the Databricks CLI's login session (DATABRICKS_PROFILE) — the
same `databricks auth login` already needed for Lakebase (see db.py). No personal
access token required; useful when an org has disabled PATs.

UNVERIFIED: written against the documented shape of `WorkspaceClient.config.authenticate()`
(designed to return request auth headers), never run against a real login session yet.
"""

from __future__ import annotations

from research_copilot.config import Settings


class FMAuthNotConfigured(RuntimeError):
    pass


def resolve_bearer_token(settings: Settings) -> str:
    if settings.fm_api_token:
        return settings.fm_api_token

    if settings.databricks_profile:
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient(profile=settings.databricks_profile)
        headers = w.config.authenticate()  # {"Authorization": "Bearer <token>", ...}
        auth_header = headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise FMAuthNotConfigured(
                f"Databricks profile {settings.databricks_profile!r} didn't return a bearer "
                "token — is `databricks auth login` complete for this profile?"
            )
        return auth_header.removeprefix("Bearer ")

    raise FMAuthNotConfigured(
        "Set DATABRICKS_FM_TOKEN, or DATABRICKS_PROFILE plus a completed `databricks auth login`."
    )
