"""Regression test for a real reported bug: searching a new topic from the
landing page left the previous topic's open reading tabs, staged (unsaved)
papers, and loaded collection all visible in the Workspace — a fresh search
is a fresh start, not a continuation of whatever was open before."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _get(at: AppTest, key: str, default):
    # AppTest.session_state doesn't support .get() the way a normal dict does.
    return at.session_state[key] if key in at.session_state else default


def test_fresh_search_clears_stale_workspace_state():
    at = AppTest.from_file("../app/Home.py", default_timeout=30)
    at.session_state["open_items"] = [{"paper_id": "W1", "paper": {}, "view": "abstract"}]
    at.session_state["active_item"] = 0
    at.session_state["staged_papers"] = {"W1": {"id": "W1", "title": "Stale Paper"}}
    at.session_state["active_collection_id"] = "11111111-1111-1111-1111-111111111111"
    at.run()

    at.text_input[0].set_value("a completely different research topic")
    search_button = next(b for b in at.button if b.label == "Search")
    search_button.click().run()

    assert not at.exception
    # A valid search calls st.switch_page, which AppTest actually follows into
    # Workspace.py within this same run — and Workspace.py's own setdefault()
    # calls immediately re-add open_items/active_item/staged_papers as empty
    # containers. That's the correct end state (no stale tabs), just not
    # "absent" — only active_collection_id (never setdefault'd) stays absent.
    assert _get(at, "open_items", []) == []
    assert not _get(at, "active_item", None)
    assert _get(at, "staged_papers", {}) == {}
    assert "active_collection_id" not in at.session_state
    assert at.session_state["search_query"] == "a completely different research topic"
