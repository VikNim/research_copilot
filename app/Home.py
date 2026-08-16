"""Screen 1 — Landing. Company name + auth in the header, a single search box below."""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from research_copilot import auth  # noqa: E402
from research_copilot.config import get_settings  # noqa: E402
from research_copilot.validation import validate_search_query  # noqa: E402

st.set_page_config(page_title="Research Copilot", page_icon="\U0001f9ed", layout="centered")

settings = get_settings()
if not settings.has_db:
    st.warning(
        "No database configured yet — set `DATABASE_URL` (local dev) or the Lakebase "
        "service-principal variables in `.env`. Search will still work; saving "
        "collections won't.",
        icon="⚠️",
    )

auth.render_header("Research Copilot")

st.write("")
st.write("")
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
        st.session_state["search_query"] = query.strip()
        st.session_state.pop("search_results", None)  # force a re-fetch on Screen 2
        st.switch_page("pages/1_Workspace.py")
