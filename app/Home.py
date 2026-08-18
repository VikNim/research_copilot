"""Screen 1 — Landing. Company name + auth in the header, a single search box below."""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)  # .env is the source of truth locally — don't let a stray shell export shadow it

from research_copilot import auth, theme  # noqa: E402
from research_copilot.config import get_settings  # noqa: E402
from research_copilot.db import session_scope  # noqa: E402
from research_copilot.repositories import goals as goals_repo  # noqa: E402
from research_copilot.validation import validate_search_query  # noqa: E402

st.set_page_config(page_title="Research Copilot", page_icon="\U0001f9ed", layout="centered")
theme.apply_theme()

settings = get_settings()
if not settings.has_db:
    st.warning(
        "No database configured yet — set `DATABASE_URL` (local dev) or the Lakebase "
        "service-principal variables in `.env`. Search will still work; saving "
        "collections won't.",
        icon="⚠️",
    )

user = auth.render_header("Research Copilot")

st.write("")
st.write("")

with st.container(key="panel-tint-1"):
    st.markdown("<h2 style='text-align:center;'>What do you want to learn?</h2>", unsafe_allow_html=True)

    with st.form("search_form"):
        query = st.text_input(
            "Topic",
            placeholder="Enter the topic you want to research or learn about",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Search", use_container_width=True)

if submitted:
    is_valid, error = validate_search_query(query)
    if not is_valid:
        st.error(error)
    else:
        clean_query = query.strip()
        st.session_state["search_query"] = clean_query
        st.session_state.pop("search_results", None)  # force a re-fetch on Screen 2

        # A fresh search from here is a fresh start in the Workspace, not a continuation
        # of whatever was open before — without this, open reading tabs, staged (not yet
        # saved) papers, and a previously loaded collection all silently carried over into
        # an unrelated new search, which read as a bug (stale tabs from the last topic
        # still showing after searching for something new).
        st.session_state.pop("open_items", None)
        st.session_state.pop("active_item", None)
        st.session_state.pop("staged_papers", None)
        st.session_state.pop("active_collection_id", None)

        # A search *is* stating a learning goal in plain language — record it so a
        # collection saved from this search can be linked back to what prompted it
        # (collections.learning_goal_id). Anonymous searches don't get one; there's
        # no user_id to attach it to, and nothing downstream needs it until Save.
        st.session_state.pop("learning_goal_id", None)
        if user is not None and settings.has_db:
            with session_scope() as session:
                goal = goals_repo.get_or_create_goal(session, user_id=user.id, title=clean_query)
                st.session_state["learning_goal_id"] = str(goal.id)

        st.switch_page("pages/1_Workspace.py")
