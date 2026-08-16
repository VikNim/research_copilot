"""Screen 2 — Workspace: matching papers (left) / reading pane (middle) / collection (right).

Two deliberate departures from the original wireframe, agreed during design review:
- Per-paper actions live behind a "⋮" popover instead of a right-click context menu
  (Streamlit has no `oncontextmenu` hook).
- The middle panel is a capped open-items list with one active selection, not true
  `st.tabs()` — Streamlit can't set the active tab from Python, and reruns the whole
  script on every interaction regardless of which tab is showing.
"""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from research_copilot import auth  # noqa: E402
from research_copilot.config import get_settings  # noqa: E402
from research_copilot.db import DatabaseNotConfigured, session_scope  # noqa: E402
from research_copilot.llm import LLMNotConfigured, chat  # noqa: E402
from research_copilot.openalex_client import OpenAlexClient, OpenAlexError  # noqa: E402
from research_copilot.repositories import collections as collections_repo  # noqa: E402
from research_copilot.repositories import papers as papers_repo  # noqa: E402

st.set_page_config(page_title="Workspace · Research Copilot", page_icon="\U0001f9ed", layout="wide")

MAX_OPEN_ITEMS = 10
settings = get_settings()

if "search_query" not in st.session_state:
    st.info("Start from the landing page — enter a topic to search for.")
    st.page_link("Home.py", label="Back to search")
    st.stop()

st.session_state.setdefault("open_items", [])  # list of {"paper_id", "mode", "paper", "summary"}
st.session_state.setdefault("active_item", None)
st.session_state.setdefault("staged_papers", {})  # paper_id -> normalized paper dict

if "search_results" not in st.session_state:
    try:
        client = OpenAlexClient()
        st.session_state["search_results"] = client.search_works(st.session_state["search_query"], per_page=15)
    except OpenAlexError as exc:
        st.error(f"OpenAlex search failed: {exc}")
        st.session_state["search_results"] = []

user = auth.render_header("Research Copilot")
st.caption(f"Results for **{st.session_state['search_query']}**")

left, mid, right = st.columns([1, 2.4, 1], gap="medium")


def _open_item(paper: dict, mode: str) -> None:
    items = st.session_state["open_items"]
    key = (paper["id"], mode)
    for item in items:
        if (item["paper_id"], item["mode"]) == key:
            st.session_state["active_item"] = items.index(item)
            return
    if len(items) >= MAX_OPEN_ITEMS:
        st.toast(f"Close something first — {MAX_OPEN_ITEMS} open items max.", icon="⚠️")
        return
    items.append({"paper_id": paper["id"], "mode": mode, "paper": paper, "summary": None})
    st.session_state["active_item"] = len(items) - 1


# --- Left panel: Query Matching Papers ---
with left:
    st.markdown("##### Query Matching Papers")
    sort_by = st.selectbox("Sort by", ["citations", "date", "name"], label_visibility="collapsed")
    results = list(st.session_state["search_results"])
    if sort_by == "citations":
        results.sort(key=lambda p: p.get("cited_by_count", 0), reverse=True)
    elif sort_by == "date":
        results.sort(key=lambda p: p.get("publication_year") or 0, reverse=True)
    else:
        results.sort(key=lambda p: (p.get("title") or "").lower())

    for paper in results:
        with st.container(border=True):
            st.markdown(f"**{paper['title'][:80]}**")
            st.caption(f"{paper.get('publication_year', '?')} · {paper.get('cited_by_count', 0)} citations")
            with st.popover("⋮"):
                if st.button("Read", key=f"read_{paper['id']}", use_container_width=True):
                    _open_item(paper, "read")
                    st.rerun()
                if st.button("Summarize", key=f"sum_{paper['id']}", use_container_width=True):
                    _open_item(paper, "summary")
                    st.rerun()
                if st.button("Add to collection", key=f"add_{paper['id']}", use_container_width=True):
                    st.session_state["staged_papers"][paper["id"]] = paper
                    st.session_state["search_results"] = [
                        p for p in st.session_state["search_results"] if p["id"] != paper["id"]
                    ]
                    st.rerun()
                if st.button("Delete", key=f"del_{paper['id']}", use_container_width=True):
                    st.session_state["search_results"] = [
                        p for p in st.session_state["search_results"] if p["id"] != paper["id"]
                    ]
                    st.rerun()

# --- Middle panel: Paper Contents / AI Summary ---
with mid:
    st.markdown("##### Paper Contents / AI Summary")
    items = st.session_state["open_items"]
    if not items:
        st.info("Open a paper from the left panel — Read or Summarize.")
    else:
        labels = [f"{'📄' if i['mode'] == 'read' else '✨'} {i['paper']['title'][:28]}…" for i in items]
        active = st.session_state["active_item"] or 0
        active = min(active, len(items) - 1)
        chosen_label = st.radio("Open items", labels, index=active, horizontal=True, label_visibility="collapsed")
        idx = labels.index(chosen_label)
        st.session_state["active_item"] = idx
        item = items[idx]
        paper = item["paper"]

        st.subheader(paper["title"])
        authors = ", ".join(a.get("display_name", "") for a in paper.get("authors", []) if a.get("display_name"))
        st.caption(f"{authors or 'Unknown authors'} · {paper.get('publication_year', '?')}")

        if item["mode"] == "read":
            st.write(paper.get("abstract") or "_No abstract available from OpenAlex for this work._")
            if paper.get("oa_pdf_url"):
                st.link_button("Open full text (external, open access)", paper["oa_pdf_url"])
            else:
                st.caption("No open-access copy indexed — full-text reading isn't in v1 anyway (abstract-only).")
        else:
            if item["summary"] is None:
                if not settings.has_fm_api:
                    st.info("AI summaries need Databricks FM API credentials (DATABRICKS_FM_BASE_URL / _TOKEN).")
                elif not paper.get("abstract"):
                    st.warning("No abstract to summarize.")
                else:
                    with st.spinner("Summarizing..."):
                        try:
                            resp = chat(
                                [
                                    {
                                        "role": "user",
                                        "content": (
                                            "Summarize this abstract in 3-4 sentences for someone new to the "
                                            f"topic. Cite it as ({authors or 'Unknown'}, {paper.get('publication_year','?')}).\n\n"
                                            f"Title: {paper['title']}\nAbstract: {paper['abstract']}"
                                        ),
                                    }
                                ]
                            )
                            item["summary"] = resp.choices[0].message.content
                        except LLMNotConfigured as exc:
                            item["summary"] = f"_{exc}_"
            if item["summary"]:
                st.write(item["summary"])

        if st.button("Close this item"):
            items.pop(idx)
            st.session_state["active_item"] = None
            st.rerun()

# --- Right panel: Collection ---
with right:
    st.markdown("##### Collection")
    staged = st.session_state["staged_papers"]
    if not staged:
        st.caption("Add papers from the left panel.")
    for paper_id, paper in list(staged.items()):
        c1, c2 = st.columns([5, 1])
        c1.write(paper["title"][:40])
        if c2.button("✕", key=f"unstage_{paper_id}"):
            del st.session_state["staged_papers"][paper_id]
            st.rerun()

    st.divider()
    collection_name = st.text_input("Collection name", value=st.session_state["search_query"].title())
    if st.button("Save Collection", type="primary", use_container_width=True, disabled=not staged):
        if user is None:
            st.warning("Log in to save a collection.")
            st.button("Log in", on_click=st.login, key="save_login")
        elif not settings.has_db:
            st.error("No database configured — set DATABASE_URL or Lakebase variables in .env.")
        else:
            try:
                with session_scope() as session:
                    collection = collections_repo.create_collection(session, user_id=user.id, name=collection_name)
                    for paper in staged.values():
                        saved = papers_repo.upsert_paper(session, paper)
                        collections_repo.add_paper(session, collection_id=collection.id, paper_id=saved.id)
                st.session_state["staged_papers"] = {}
                st.success(f"Saved “{collection_name}” with {len(staged)} paper(s).")
                st.page_link("pages/2_Profile.py", label="View in your profile")
            except DatabaseNotConfigured as exc:
                st.error(str(exc))
