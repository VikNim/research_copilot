"""Environment-driven settings. No secrets are hardcoded; everything comes from
the environment (or a local .env file loaded by dotenv in app entrypoints)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


EMBEDDING_DIM = 1024  # Qwen3-Embedding-0.6B default output size (MRL range: 32-1024)


@dataclass(frozen=True)
class Settings:
    # --- Database ---
    # Local/dev escape hatch: a plain Postgres URL (used by `uv run streamlit run app/Home.py`
    # during development, and by the test suite against a local pgvector-enabled Postgres).
    database_url: str | None = field(default_factory=lambda: os.environ.get("DATABASE_URL"))

    # Lakebase (production path): short-lived credentials, never a static password.
    # Two ways to mint them (see db.py):
    #   - Personal OAuth via the Databricks CLI profile (`databricks auth login`) — what's
    #     actually configured for this workspace right now. WorkspaceClient(profile=...)
    #     refreshes automatically once that login is valid.
    #   - A service principal (client_id/secret) — better for a deployed/hosted app later.
    databricks_host: str | None = field(default_factory=lambda: os.environ.get("DATABRICKS_HOST"))
    databricks_profile: str | None = field(default_factory=lambda: os.environ.get("DATABRICKS_PROFILE"))
    databricks_client_id: str | None = field(default_factory=lambda: os.environ.get("DATABRICKS_CLIENT_ID"))
    databricks_client_secret: str | None = field(default_factory=lambda: os.environ.get("DATABRICKS_CLIENT_SECRET"))
    lakebase_instance_name: str | None = field(default_factory=lambda: os.environ.get("LAKEBASE_INSTANCE_NAME"))
    lakebase_host: str | None = field(default_factory=lambda: os.environ.get("LAKEBASE_HOST"))
    lakebase_db_name: str = field(default_factory=lambda: os.environ.get("LAKEBASE_DB_NAME", "databricks_postgres"))
    lakebase_db_user: str | None = field(default_factory=lambda: os.environ.get("LAKEBASE_DB_USER"))
    lakebase_port: int = field(default_factory=lambda: int(os.environ.get("LAKEBASE_PORT", "5432")))

    # Manual escape hatch only: a hand-pasted OAuth token, valid ~1hr, never auto-refreshed.
    # Useful for a one-off connectivity check; not meant to back the running app.
    lakebase_static_token: str | None = field(default_factory=lambda: os.environ.get("LAKEBASE_STATIC_TOKEN"))

    # --- Databricks Foundation Model APIs (agent LLM + embeddings) ---
    fm_api_base_url: str | None = field(default_factory=lambda: os.environ.get("DATABRICKS_FM_BASE_URL"))
    fm_api_token: str | None = field(default_factory=lambda: os.environ.get("DATABRICKS_FM_TOKEN"))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "databricks-claude-haiku-4-5"))
    embedding_model: str = field(default_factory=lambda: os.environ.get("EMBEDDING_MODEL", "databricks-qwen3-embedding-0-6b"))

    # --- OpenAlex ---
    openalex_api_key: str | None = field(default_factory=lambda: os.environ.get("OPENALEX_API_KEY"))
    openalex_mailto: str | None = field(default_factory=lambda: os.environ.get("OPENALEX_MAILTO"))

    @property
    def has_local_db(self) -> bool:
        return bool(self.database_url)

    @property
    def has_lakebase_credential_flow(self) -> bool:
        """The real path: mint a fresh short-lived credential on every connection."""
        has_auth = bool(self.databricks_profile or (self.databricks_client_id and self.databricks_client_secret))
        return bool(has_auth and self.lakebase_instance_name and self.lakebase_host and self.lakebase_db_user)

    @property
    def has_lakebase_static_token(self) -> bool:
        """The manual escape hatch: a hand-pasted token, good for ~1hr."""
        return bool(self.lakebase_static_token and self.lakebase_host and self.lakebase_db_user)

    @property
    def has_lakebase(self) -> bool:
        return self.has_lakebase_credential_flow or self.has_lakebase_static_token

    @property
    def has_db(self) -> bool:
        return self.has_local_db or self.has_lakebase

    @property
    def has_fm_api(self) -> bool:
        return bool(self.fm_api_base_url and (self.fm_api_token or self.databricks_profile))


def get_settings() -> Settings:
    return Settings()
