"""chat()'s primary -> fallback proxy failover, tested against the real openai
SDK exception types (not a hand-rolled stand-in) but with fake clients standing
in for the network call — the branching logic is what's under test here, not
whether a real proxy is reachable."""

from __future__ import annotations

from unittest.mock import Mock

import openai
import pytest

from research_copilot import llm


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


def _fake_auth_error() -> openai.AuthenticationError:
    request = Mock()
    response = Mock(status_code=401, headers={}, request=request)
    return openai.AuthenticationError("Monthly token limit exceeded", response=response, body=None)


def test_chat_fails_over_to_fallback_proxy_on_primary_auth_error(monkeypatch):
    primary_client = Mock()
    primary_client.chat.completions.create.side_effect = _fake_auth_error()

    fallback_client = Mock()
    fallback_client.chat.completions.create.return_value = _FakeResponse("from fallback")

    monkeypatch.setattr(llm, "_primary_client_and_model", lambda settings: (primary_client, "gpt-4o"))
    monkeypatch.setattr(llm, "_fallback_client_and_model", lambda settings: (fallback_client, "claude-3-5-sonnet"))

    result = llm.chat([{"role": "user", "content": "hi"}], settings=object())

    assert result.content == "from fallback"
    primary_client.chat.completions.create.assert_called_once()
    assert primary_client.chat.completions.create.call_args.kwargs["model"] == "gpt-4o"
    fallback_client.chat.completions.create.assert_called_once()
    assert fallback_client.chat.completions.create.call_args.kwargs["model"] == "claude-3-5-sonnet"


def test_chat_reraises_when_primary_fails_and_no_fallback_is_configured(monkeypatch):
    primary_client = Mock()
    primary_client.chat.completions.create.side_effect = _fake_auth_error()

    monkeypatch.setattr(llm, "_primary_client_and_model", lambda settings: (primary_client, "gpt-4o"))
    monkeypatch.setattr(llm, "_fallback_client_and_model", lambda settings: None)

    with pytest.raises(openai.AuthenticationError):
        llm.chat([{"role": "user", "content": "hi"}], settings=object())


def test_chat_does_not_touch_fallback_when_primary_succeeds(monkeypatch):
    primary_client = Mock()
    primary_client.chat.completions.create.return_value = _FakeResponse("from primary")

    fallback_client = Mock()

    monkeypatch.setattr(llm, "_primary_client_and_model", lambda settings: (primary_client, "gpt-4o"))
    monkeypatch.setattr(llm, "_fallback_client_and_model", lambda settings: (fallback_client, "claude-3-5-sonnet"))

    result = llm.chat([{"role": "user", "content": "hi"}], settings=object())

    assert result.content == "from primary"
    fallback_client.chat.completions.create.assert_not_called()
