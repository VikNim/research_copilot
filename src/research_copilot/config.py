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

    # --- Databricks Foundation Model APIs (embeddings always; chat when no proxy below is set) ---
    fm_api_base_url: str | None = field(default_factory=lambda: os.environ.get("DATABRICKS_FM_BASE_URL"))
    fm_api_token: str | None = field(default_factory=lambda: os.environ.get("DATABRICKS_FM_TOKEN"))
    # LLM_MODEL's meaning depends on which chat backend is active: the Databricks model
    # id (e.g. "databricks-claude-haiku-4-5") normally, or the proxy's own model name
    # once CHAT_PROXY_BASE_URL/CHAT_PROXY_API_KEY are set — see llm.py.
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "databricks-claude-haiku-4-5"))
    embedding_model: str = field(default_factory=lambda: os.environ.get("EMBEDDING_MODEL", "databricks-qwen3-embedding-0-6b"))

    # --- Chat LLM proxy (optional): an OpenAI-compatible endpoint that replaces the
    # Databricks model for chat only — the agent, summaries, and reading plans go
    # through this when set. Embeddings/semantic search are untouched and stay on
    # Databricks regardless, since this proxy has no embeddings endpoint of its own.
    chat_proxy_base_url: str | None = field(default_factory=lambda: os.environ.get("CHAT_PROXY_BASE_URL"))
    chat_proxy_api_key: str | None = field(default_factory=lambda: os.environ.get("CHAT_PROXY_API_KEY"))

    # --- Chat LLM fallback proxy (optional): tried only if the primary proxy call
    # above fails with an auth/quota error (see llm.py) — a separate model needs its
    # own model id, since it won't be the same model name as the primary proxy's.
    chat_fallback_proxy_base_url: str | None = field(default_factory=lambda: os.environ.get("CHAT_FALLBACK_PROXY_BASE_URL"))
    chat_fallback_proxy_api_key: str | None = field(default_factory=lambda: os.environ.get("CHAT_FALLBACK_PROXY_API_KEY"))
    chat_fallback_model: str | None = field(default_factory=lambda: os.environ.get("CHAT_FALLBACK_MODEL"))

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
        """Databricks FM API specifically — embeddings/semantic search always need
        this (the chat proxy below has no embeddings endpoint), regardless of which
        backend is handling chat. Chat-gating code should check has_chat_llm instead."""
        has_auth = bool(
            self.fm_api_token
            or self.databricks_profile
            or (self.databricks_client_id and self.databricks_client_secret)
        )
        return bool(self.fm_api_base_url and has_auth)

    @property
    def has_chat_proxy(self) -> bool:
        return bool(self.chat_proxy_base_url and self.chat_proxy_api_key)

    @property
    def has_chat_fallback_proxy(self) -> bool:
        return bool(self.chat_fallback_proxy_base_url and self.chat_fallback_proxy_api_key and self.chat_fallback_model)

    @property
    def has_chat_llm(self) -> bool:
        """Whatever's actually available for chat — the proxy, if configured
        (llm.py prefers it), otherwise Databricks. Use this (not has_fm_api) to
        gate chat/summarize/agent UI; use has_fm_api for embeddings-only gating."""
        return self.has_chat_proxy or self.has_fm_api


def get_settings() -> Settings:
    return Settings()


def load_cloud_secrets() -> None:
    """Streamlit Community Cloud has no .env file — secrets are pasted into its
    dashboard as TOML and exposed via st.secrets instead. Every Settings field
    above reads from os.environ, so bridge st.secrets into it here rather than
    teaching each field two lookup paths. Call once per entrypoint, after
    load_dotenv(override=True).

    No-op locally: [auth] (Google OAuth) is the only thing in a local
    secrets.toml today, and it's a nested table, not a flat string value, so
    the isinstance check below skips it — nothing here overrides a local .env.
    """
    import streamlit as st

    try:
        secrets = st.secrets
    except Exception:
        return
    for key, value in secrets.items():
        if isinstance(value, str):
            os.environ[key] = value
