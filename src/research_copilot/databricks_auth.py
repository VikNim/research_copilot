"""Shared bearer-token resolution for calling Databricks Foundation Model APIs —
used by both llm.py and embeddings.py.

Three paths, in order:
  - DATABRICKS_FM_TOKEN: a static PAT. Not an option for this org (PATs disabled).
  - DATABRICKS_PROFILE: mints a token from the Databricks CLI's own OAuth login
    session. Works great locally; needs `databricks auth login` to already be
    complete, which is interactive/browser-based and ties the token to whatever
    machine ran it — this path does not exist on a deployed server (Streamlit
    Community Cloud, etc.), which has no access to that local CLI session.
  - DATABRICKS_CLIENT_ID/DATABRICKS_CLIENT_SECRET: a service-principal OAuth
    client-credentials flow — headless, no browser, no local CLI state needed.
    This is the one that actually works once deployed. Same client_id/secret
    db.py's Lakebase credential-flow already supports; mirrored here so both
    Lakebase and the FM API can run off the same service principal.
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
        return _bearer_from(w, f"Databricks profile {settings.databricks_profile!r}")

    if settings.databricks_client_id and settings.databricks_client_secret:
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient(
            host=settings.databricks_host,
            client_id=settings.databricks_client_id,
            client_secret=settings.databricks_client_secret,
        )
        return _bearer_from(w, "the configured service principal")

    raise FMAuthNotConfigured(
        "Set DATABRICKS_FM_TOKEN, DATABRICKS_PROFILE plus a completed `databricks auth "
        "login`, or DATABRICKS_HOST/DATABRICKS_CLIENT_ID/DATABRICKS_CLIENT_SECRET for a "
        "service principal (the one that works on a deployed server)."
    )


def _bearer_from(w, source_desc: str) -> str:
    headers = w.config.authenticate()  # {"Authorization": "Bearer <token>", ...}
    auth_header = headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise FMAuthNotConfigured(f"{source_desc} didn't return a bearer token.")
    return auth_header.removeprefix("Bearer ")
