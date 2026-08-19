"""has_chat_proxy/has_fm_api/has_chat_llm gate two independent things (chat vs.
embeddings) — a regression here silently breaks either the wrong feature or the
wrong provider selection, so it's worth locking in directly rather than only
exercising it indirectly through llm.py.

Every field that feeds has_fm_api/has_chat_proxy is passed explicitly in each
case below — Settings' fields default to reading the *real* os.environ (see
config.py's default_factory=lambda: os.environ.get(...)), so leaving any of
them unset here would silently pull in whatever this session's real .env
happens to have, rather than testing the four cases in isolation."""

from __future__ import annotations

from research_copilot.config import Settings

_NONE_FM_FIELDS = dict(
    fm_api_base_url=None, fm_api_token=None, databricks_profile=None,
    databricks_client_id=None, databricks_client_secret=None,
    chat_proxy_base_url=None, chat_proxy_api_key=None,
)


def test_chat_proxy_and_databricks_fm_are_independent():
    # proxy only -> chat available, embeddings (has_fm_api) are not
    proxy_only = Settings(**{**_NONE_FM_FIELDS, "chat_proxy_base_url": "https://proxy.test/v1", "chat_proxy_api_key": "k"})
    assert proxy_only.has_chat_proxy is True
    assert proxy_only.has_fm_api is False
    assert proxy_only.has_chat_llm is True

    # Databricks only -> chat available via Databricks, embeddings available too
    databricks_only = Settings(**{**_NONE_FM_FIELDS, "fm_api_base_url": "https://dbc.test/serving-endpoints", "fm_api_token": "t"})
    assert databricks_only.has_chat_proxy is False
    assert databricks_only.has_fm_api is True
    assert databricks_only.has_chat_llm is True

    # neither -> nothing available
    neither = Settings(**_NONE_FM_FIELDS)
    assert neither.has_chat_proxy is False
    assert neither.has_fm_api is False
    assert neither.has_chat_llm is False

    # both -> chat still counts as available (llm.py prefers the proxy); embeddings
    # stay on Databricks regardless, since the proxy has no embeddings endpoint
    both = Settings(**{
        **_NONE_FM_FIELDS,
        "chat_proxy_base_url": "https://proxy.test/v1", "chat_proxy_api_key": "k",
        "fm_api_base_url": "https://dbc.test/serving-endpoints", "fm_api_token": "t",
    })
    assert both.has_chat_proxy is True
    assert both.has_fm_api is True
    assert both.has_chat_llm is True
