"""Screen 3 — User Profile page (route-guarded, no auth buttons) + 3a Collection Detail,
opened as a separate view when a tile is clicked rather than expanding inline."""

from __future__ import annotations

import uuid

import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)  # .env is the source of truth locally — don't let a stray shell export shadow it

from research_copilot import auth, chat_ui, theme  # noqa: E402
from research_copilot.config import get_settings  # noqa: E402
from research_copilot.db import session_scope  # noqa: E402
from research_copilot.repositories import collections as collections_repo  # noqa: E402
from research_copilot.repositories import notes as notes_repo  # noqa: E402
from research_copilot.repositories import progress as progress_repo  # noqa: E402

st.set_page_config(page_title="Profile · Research Copilot", page_icon="\U0001f9ed", layout="wide")
theme.apply_theme()

settings = get_settings()
if not settings.has_db:
    st.warning("No database configured — set DATABASE_URL or Lakebase variables in .env.", icon="⚠️")
    st.stop()

user = auth.require_login("Research Copilot")

with session_scope() as session:
    collections = collections_repo.list_collections_for_user(session, user.id)
    collections_data = [{"id": c.id, "name": c.name} for c in collections]

selected_id = st.session_state.get("selected_collection_id")

if not selected_id:
    with st.container(key="panel-tint-1"):
        st.markdown("##### Your collections")
        if not collections_data:
            st.info("No collections yet — save one from the Workspace search results.")
        else:
            cols = st.columns(min(len(collections_data), 5) or 1)
            for i, c in enumerate(collections_data):
                if cols[i % len(cols)].button(c["name"], key=f"tile_{c['id']}", use_container_width=True):
                    st.session_state["selected_collection_id"] = str(c["id"])
                    st.rerun()
else:
    collection_id = uuid.UUID(selected_id)
    with session_scope() as session:
        collection = collections_repo.get_collection(session, collection_id)
        if collection is None or collection.user_id != user.id:
            st.error("Collection not found.")
            st.session_state.pop("selected_collection_id", None)
            st.stop()

        b1, b2 = st.columns([1, 1])
        if b1.button("← Back to collections"):
            st.session_state.pop("selected_collection_id", None)
            st.rerun()
        if b2.button("Open in Workspace →", type="primary"):
            st.session_state["active_collection_id"] = str(collection_id)
            st.session_state.pop("search_results", None)
            st.session_state.pop("open_items", None)
            st.session_state["active_item"] = None
            st.switch_page("pages/1_Workspace.py")

        st.markdown(f"##### {collection.name}")

        # Reading plans and "where should I start" are now asked of the agent chat
        # below (suggested prompts included) instead of a dedicated button here —
        # one surface for that capability instead of two ways to trigger the same
        # thing with slightly different UX.

        with st.container(key="panel-tint-3"):
            st.markdown("**Collection notes** _(about the topic as a whole)_")
            collection_notes = notes_repo.list_for_collection(session, user_id=user.id, collection_id=collection_id)
            for n in collection_notes:
                st.caption(f"{n.created_at:%Y-%m-%d}: {n.content}")
            new_note = st.text_input("Add a collection note", key="new_collection_note", max_chars=20000)
            if st.button("Add note", key="add_collection_note") and new_note.strip():
                # A separate session_scope, committed before rerun fires: st.rerun()
                # raises a BaseException Streamlit uses to unwind the script, which
                # skips session_scope's `except Exception` handler entirely — calling
                # it while still inside the *outer* session's `with` block would
                # close that session without ever reaching its commit, silently
                # discarding the write.
                with session_scope() as write_session:
                    notes_repo.add_note(write_session, user_id=user.id, collection_id=collection_id, content=new_note.strip())
                st.rerun()

        st.divider()
        with st.container(key="panel-tint-4"):
            st.markdown("**Papers**")
            papers = collections_repo.list_papers_in_collection(session, collection_id)
            progress_by_paper = progress_repo.list_for_collection(session, user_id=user.id, collection_id=collection_id)

            statuses = ["not_started", "in_progress", "done"]
            for paper in papers:
                authors = ", ".join(link.author.display_name for link in paper.authors if link.author.display_name)
                current = progress_by_paper.get(paper.id)
                current_status = current.status if current else "not_started"
                # Fetched once, above the fold — both the badge in c1 and the
                # expander below read from this, instead of querying twice.
                paper_notes = notes_repo.list_for_paper(session, user_id=user.id, paper_id=paper.id)
                has_summary = any(n.content.startswith(f"**{notes_repo.AI_SUMMARY_LABEL}**") for n in paper_notes)

                with st.container(border=True, key=f"card-profile-paper-{paper.id}"):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.write(f"**{paper.title}**" + (f" {notes_repo.AI_SUMMARY_LABEL}" if has_summary else ""))
                        st.caption(authors or "Unknown authors")
                    with c2:
                        new_status = st.selectbox(
                            "Progress", statuses, index=statuses.index(current_status),
                            format_func=lambda s: progress_repo.STATUS_LABELS[s],
                            key=f"status_{paper.id}", label_visibility="collapsed",
                        )
                        if new_status != current_status:
                            # Own session_scope, committed before rerun — see the
                            # collection-notes button above for why.
                            with session_scope() as write_session:
                                progress_repo.set_status(
                                    write_session, user_id=user.id, paper_id=paper.id,
                                    status=new_status, collection_id=collection_id,
                                )
                            st.rerun()

                    with st.expander("Notes for this paper"):
                        for n in paper_notes:
                            st.caption(f"{n.created_at:%Y-%m-%d}: {n.content}")
                        note_text = st.text_input("Add a note", key=f"note_input_{paper.id}", max_chars=20000)
                        if st.button("Add", key=f"note_add_{paper.id}") and note_text.strip():
                            with session_scope() as write_session:
                                notes_repo.add_note(write_session, user_id=user.id, paper_id=paper.id, content=note_text.strip())
                            st.rerun()

        collection_name = collection.name

    # Outside the read session on purpose (expire_on_commit=False keeps collection_name
    # usable regardless, but the chat's own agent turn shouldn't run inside — and hold
    # open — a connection this page only needed for the reads above). Same component
    # Workspace.py's loaded-collection view uses — see chat_ui.py.
    st.divider()
    chat_ui.render_agent_chat(collection_id, collection_name, user)
