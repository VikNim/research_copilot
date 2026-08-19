"""Screen 2 — Workspace: matching papers (left) / reading pane (middle) / collection (right).

Two deliberate departures from the original wireframe, agreed during design review:
- Per-paper actions live behind a "⋮" popover instead of a right-click context menu
  (Streamlit has no `oncontextmenu` hook).
- The middle panel is a capped open-items list with one active selection, not true
  `st.tabs()` — Streamlit can't set the active tab from Python, and reruns the whole
  script on every interaction regardless of which tab is showing.

Two modes for the right panel, chosen by `active_collection_id` in session_state:
- Discovery mode (default, arrived via a fresh search): papers are staged locally and
  only persisted when "Save Collection" is clicked.
- Loaded-collection mode (arrived via "Open in Workspace" on the Profile page): the
  right panel shows the real, already-saved collection; adding a paper persists
  immediately, and the Read view carries that collection's notes + reading progress.
"""

from __future__ import annotations

import uuid

import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)  # .env is the source of truth locally — don't let a stray shell export shadow it

from research_copilot import auth, chat_ui, fulltext, semantic, theme  # noqa: E402
from research_copilot.config import get_settings, load_cloud_secrets  # noqa: E402
from research_copilot.db import DatabaseNotConfigured, session_scope  # noqa: E402
from research_copilot.embeddings import EmbeddingsNotConfigured  # noqa: E402
from research_copilot.llm import LLMNotConfigured, chat  # noqa: E402
from research_copilot.openalex_client import OpenAlexClient, OpenAlexError  # noqa: E402
from research_copilot.repositories import collections as collections_repo  # noqa: E402
from research_copilot.repositories import notes as notes_repo  # noqa: E402
from research_copilot.repositories import papers as papers_repo  # noqa: E402
from research_copilot.repositories import progress as progress_repo  # noqa: E402

load_cloud_secrets()  # Streamlit Cloud has no .env — bridges st.secrets into os.environ instead

st.set_page_config(page_title="Workspace · Research Copilot", page_icon="\U0001f9ed", layout="wide")
theme.apply_theme()

MAX_OPEN_ITEMS = 10
VIEW_LABELS = {"abstract": "Abstract", "full_text": "Full text", "summary": "Summary"}
settings = get_settings()

active_collection_id: uuid.UUID | None = None
if st.session_state.get("active_collection_id"):
    active_collection_id = uuid.UUID(st.session_state["active_collection_id"])

if "search_query" not in st.session_state and active_collection_id is None:
    st.info("Start from the landing page — enter a topic to search for.")
    st.page_link("Home.py", label="Back to search")
    st.stop()

st.session_state.setdefault("open_items", [])  # list of {"paper_id", "paper", "view", "summary",
                                                 # "summary_source", "full_text", "full_text_tried"} —
                                                 # one entry per paper (not per paper+mode); "view" picks
                                                 # which of abstract/full_text/summary is showing.
st.session_state.setdefault("active_item", None)
st.session_state.setdefault("staged_papers", {})  # paper_id -> normalized paper dict (discovery mode only)

if "search_query" in st.session_state and "search_results" not in st.session_state:
    try:
        client = OpenAlexClient()
        results = client.search_works(st.session_state["search_query"], per_page=15)
        if settings.has_db:
            # Cache-through: every OpenAlex result gets a papers row immediately (cheap —
            # no embedding call here), so it's ready for semantic ranking or a collection
            # add without a second fetch. See semantic.py for the embedding step, which
            # only runs when semantic ranking is actually requested.
            with session_scope() as session:
                for r in results:
                    papers_repo.upsert_paper(session, r)
        st.session_state["search_results"] = results
    except OpenAlexError as exc:
        st.error(f"OpenAlex search failed: {exc}")
        st.session_state["search_results"] = []

user = auth.render_header("Research Copilot")

def _normalize_db_paper(p) -> dict:
    return {
        "id": p.id, "title": p.title, "abstract": p.abstract,
        "publication_year": p.publication_year, "oa_pdf_url": p.oa_pdf_url,
        "authors": [{"display_name": link.author.display_name} for link in p.authors],
    }


def _new_item(paper: dict, view: str) -> dict:
    return {
        "paper_id": paper["id"], "paper": paper, "view": view,
        "summary": None, "summary_source": None,
        "full_text": None, "full_text_tried": False,
    }


active_collection = None
if active_collection_id is not None and settings.has_db and user is not None:
    with session_scope() as session:
        # get_owned_collection, not get_collection: active_collection_id comes from
        # session_state, which — while not directly user-editable in normal use —
        # shouldn't be trusted as proof of ownership on its own. See collections_repo.
        c = collections_repo.get_owned_collection(session, active_collection_id, user.id)
        if c is not None:
            active_collection = {"id": c.id, "name": c.name}
            # First time landing here with this collection: open every paper it
            # already has (up to the cap) so notes/summaries are visible immediately,
            # rather than requiring a click per paper just to see what's there.
            if not st.session_state["open_items"]:
                for p in collections_repo.list_papers_in_collection(session, active_collection_id)[:MAX_OPEN_ITEMS]:
                    st.session_state["open_items"].append(_new_item(_normalize_db_paper(p), "abstract"))
                if st.session_state["open_items"]:
                    st.session_state["active_item"] = 0
        else:
            # Ownership check failed (or the id no longer exists) — invalidate it
            # everywhere on this page, not just for display. Without this, later
            # code (e.g. _add_to_collection) would still trust the raw id for writes.
            st.session_state.pop("active_collection_id", None)
            active_collection_id = None

if active_collection:
    st.caption(f"Working in collection **{active_collection['name']}** — search below to add more papers to it.")
    if st.button("← Exit collection, back to plain search"):
        st.session_state.pop("active_collection_id", None)
        st.rerun()
elif "search_query" in st.session_state:
    st.caption(f"Results for **{st.session_state['search_query']}**")

left, mid, right = st.columns([1, 2.4, 1], gap="medium")


def _open_item(paper: dict, view: str) -> None:
    """One open item per paper, not per paper+view — Read and Summarize on an
    already-open paper switch its view instead of opening a second tab for the
    same paper (that used to double up on every paper with both actions used)."""
    items = st.session_state["open_items"]
    for i, item in enumerate(items):
        if item["paper_id"] == paper["id"]:
            item["view"] = view
            # The content-view segmented_control below has a stable key (so it
            # remembers a manual tab switch across reruns) — which also means it
            # ignores `default` after its first render, so switching the view here
            # needs to write straight into its backing session_state key too, or
            # clicking Summarize on an already-open paper wouldn't visibly switch
            # the tab.
            st.session_state[f"content_view_{paper['id']}"] = VIEW_LABELS[view]
            st.session_state["active_item"] = i
            return
    if len(items) >= MAX_OPEN_ITEMS:
        st.toast(f"Close something first — {MAX_OPEN_ITEMS} open items max.", icon="⚠️")
        return
    items.append(_new_item(paper, view))
    st.session_state[f"content_view_{paper['id']}"] = VIEW_LABELS[view]
    st.session_state["active_item"] = len(items) - 1

    if active_collection_id is not None and user is not None:
        with session_scope() as session:
            progress_repo.mark_started(
                session, user_id=user.id, paper_id=paper["id"], collection_id=active_collection_id
            )


def _add_to_collection(paper: dict, summary: str | None = None) -> None:
    """Adds a paper to the collection — persists immediately in loaded-collection
    mode, otherwise stages it locally for the eventual "Save Collection" click."""
    if active_collection_id is not None and user is not None and settings.has_db:
        with session_scope() as session:
            saved = papers_repo.upsert_paper(session, paper)
            collections_repo.add_paper(session, collection_id=active_collection_id, paper_id=saved.id)
            if summary:
                notes_repo.add_note(
                    session, user_id=user.id, paper_id=saved.id, content=notes_repo.format_summary_note(summary)
                )
        verb = "paper and its summary" if summary else "paper"
        st.toast(f"Added the {verb} to {active_collection['name']}.", icon="✅")
    else:
        paper = dict(paper)
        if summary:
            paper["_pending_summary"] = summary
        st.session_state["staged_papers"][paper["id"]] = paper
    if "search_results" in st.session_state:
        st.session_state["search_results"] = [
            p for p in st.session_state["search_results"] if p["id"] != paper["id"]
        ]


# --- Left panel: Query Matching Papers ---
with left:
    with st.container(key="panel-tint-1"):
        st.markdown("##### Query Matching Papers")
        results = list(st.session_state.get("search_results", []))
        if not results:
            if "search_results" in st.session_state:
                # Distinct from "haven't searched yet" — this is a real search that
                # genuinely found nothing on OpenAlex, not a blank first-load state.
                st.caption(
                    "No papers found for this exact phrasing. Try fewer or more "
                    "general words — OpenAlex's search does better with a short "
                    "phrase than a full sentence."
                )
            else:
                st.caption("Search from the landing page to find papers" + (" to add here." if active_collection else "."))
        else:
            sort_options = ["citations", "date", "name"]
            if settings.has_fm_api and settings.has_db:
                sort_options.append("semantic match")
            sort_by = st.selectbox("Sort by", sort_options, label_visibility="collapsed")

            if sort_by == "citations":
                results.sort(key=lambda p: p.get("cited_by_count", 0), reverse=True)
            elif sort_by == "date":
                results.sort(key=lambda p: p.get("publication_year") or 0, reverse=True)
            elif sort_by == "name":
                results.sort(key=lambda p: (p.get("title") or "").lower())
            else:
                query = st.session_state.get("search_query", "")
                cache = st.session_state.setdefault("semantic_rank_cache", {})
                if query not in cache:
                    with st.spinner("Ranking by meaning, not just keywords..."):
                        try:
                            with session_scope() as session:
                                cache[query] = semantic.semantic_rank(
                                    session, [p["id"] for p in results], query
                                )
                        except EmbeddingsNotConfigured as exc:
                            st.warning(str(exc))
                            cache[query] = [p["id"] for p in results]
                order = {pid: i for i, pid in enumerate(cache[query])}
                results.sort(key=lambda p: order.get(p["id"], len(order)))

            # Fixed height -> Streamlit scrolls this box internally instead of the
            # whole page, so the list is browsable without losing the heading/sort
            # controls above it. border=False: panel-tint-1 already draws one.
            with st.container(height=560, border=False, key="results-scroll"):
                for paper in results:
                    with st.container(border=True, key=f"card-search-{paper['id']}"):
                        st.markdown(f"**{paper['title'][:80]}**")
                        st.caption(f"{paper.get('publication_year', '?')} · {paper.get('cited_by_count', 0)} citations")
                        with st.popover("⋮"):
                            if st.button("Read", key=f"read_{paper['id']}", use_container_width=True):
                                _open_item(paper, "abstract")
                                st.rerun()
                            if st.button("Summarize", key=f"sum_{paper['id']}", use_container_width=True):
                                _open_item(paper, "summary")
                                st.rerun()
                            if st.button("Add to collection", key=f"add_{paper['id']}", use_container_width=True):
                                _add_to_collection(paper)
                                st.rerun()
                            if st.button("Delete", key=f"del_{paper['id']}", use_container_width=True):
                                st.session_state["search_results"] = [
                                    p for p in st.session_state["search_results"] if p["id"] != paper["id"]
                                ]
                                st.rerun()

# --- Middle panel: Paper Contents / AI Summary ---

def _get_full_text_for_item(item: dict) -> str | None:
    """Fetches (or returns cached) full text for the item's paper. Needs a
    database — that's also what the extraction cache itself is stored in, same
    precondition semantic-match sort already has."""
    if item["full_text_tried"]:
        return item["full_text"]
    item["full_text_tried"] = True
    if not settings.has_db:
        return None
    with session_scope() as session:
        paper_row = papers_repo.get_paper(session, item["paper_id"])
        if paper_row is None:
            return None
        text = fulltext.ensure_full_text(session, paper_row)
    item["full_text"] = text
    return text


with mid:
    with st.container(key="panel-tint-2"):
        st.markdown("##### Paper Contents / AI Summary")
        items = st.session_state["open_items"]
        if not items:
            st.info("Open a paper from the left panel — Read or Summarize.")
        else:
            view_icons = {"abstract": "📄", "full_text": "📚", "summary": "✨"}
            labels = [f"{view_icons[i['view']]} {i['paper']['title'][:24]}…" for i in items]
            active = st.session_state["active_item"] or 0
            active = min(active, len(items) - 1)
            chosen_label = st.segmented_control(
                "Open items", labels, default=labels[active], label_visibility="collapsed"
            )
            idx = labels.index(chosen_label) if chosen_label in labels else active
            st.session_state["active_item"] = idx
            item = items[idx]
            paper = item["paper"]

            st.subheader(paper["title"])
            authors = ", ".join(a.get("display_name", "") for a in paper.get("authors", []) if a.get("display_name"))
            st.caption(f"{authors or 'Unknown authors'} · {paper.get('publication_year', '?')}")

            chosen_view_label = st.segmented_control(
                "Content", list(VIEW_LABELS.values()), default=VIEW_LABELS[item["view"]],
                key=f"content_view_{paper['id']}", label_visibility="collapsed",
            )
            view_by_label = {v: k for k, v in VIEW_LABELS.items()}
            item["view"] = view_by_label.get(chosen_view_label, item["view"])

            with st.container(height=380, border=True, key="card-reading-pane"):
                if item["view"] == "abstract":
                    # abstract and OA full text are independent facts from OpenAlex — a paper
                    # can be missing either, both, or neither, so state exactly what's known
                    # instead of stacking two messages that read as contradictory together.
                    has_abstract = bool(paper.get("abstract"))
                    has_oa_pdf = bool(paper.get("oa_pdf_url"))

                    if has_abstract:
                        st.write(paper["abstract"])
                    elif has_oa_pdf:
                        st.caption("No abstract indexed for this paper. Try the Full text tab.")
                    else:
                        st.caption("OpenAlex has neither an abstract nor an open-access copy indexed for this paper.")

                elif item["view"] == "full_text":
                    if not paper.get("oa_pdf_url"):
                        st.caption("No open-access PDF indexed for this paper — full text isn't available.")
                    elif not settings.has_db:
                        st.caption("Full-text fetching needs a database configured.")
                    else:
                        with st.spinner("Fetching full text..."):
                            text = _get_full_text_for_item(item)
                        if text:
                            st.caption(f"{len(text):,} characters extracted from the open-access PDF.")
                            st.write(text)
                        else:
                            st.caption(
                                "Couldn't extract full text from this paper's open-access link — it may not be a "
                                "direct PDF, or the PDF may be scanned images rather than real text."
                            )
                            st.link_button("Open the source link", paper["oa_pdf_url"])

                else:  # summary
                    if item["summary"] is None:
                        if not settings.has_chat_llm:
                            st.info("AI summaries need a chat LLM configured (Databricks FM API or the chat proxy).")
                        else:
                            with st.spinner("Checking for full text..."):
                                source_text = _get_full_text_for_item(item)
                            source = "full_text" if source_text else "abstract"
                            source_text = source_text or paper.get("abstract")
                            if not source_text:
                                st.warning("No full text or abstract available to summarize.")
                            else:
                                st.caption(
                                    "⏳ First summary can take a few seconds (longer for a full paper) — stay on "
                                    "this item until it finishes, switching to something else will restart it."
                                )
                                with st.spinner("Summarizing..."):
                                    try:
                                        if source == "full_text":
                                            prompt = (
                                                "Summarize this paper in 5-8 sentences for someone new to the topic, "
                                                "covering its core claim, method, and finding. Cite it as "
                                                f"({authors or 'Unknown'}, {paper.get('publication_year', '?')}).\n\n"
                                                f"Title: {paper['title']}\nFull text: {source_text}"
                                            )
                                        else:
                                            prompt = (
                                                "Summarize this abstract in 3-4 sentences for someone new to the "
                                                f"topic. Cite it as ({authors or 'Unknown'}, "
                                                f"{paper.get('publication_year', '?')}).\n\n"
                                                f"Title: {paper['title']}\nAbstract: {source_text}"
                                            )
                                        resp = chat([{"role": "user", "content": prompt}])
                                        item["summary"] = resp.choices[0].message.content
                                        item["summary_source"] = source
                                    except LLMNotConfigured as exc:
                                        item["summary"] = f"_{exc}_"
                    if item["summary"]:
                        if item["summary_source"] == "abstract":
                            st.caption("Summarized from the abstract — no open-access full text available.")
                        elif item["summary_source"] == "full_text":
                            st.caption("Summarized from the paper's full text.")
                        st.write(item["summary"])

            if item["view"] == "summary" and item["summary"]:
                if st.button("Add paper + summary to collection", key=f"add_summary_{paper['id']}"):
                    _add_to_collection(paper, summary=item["summary"])
                    st.rerun()

            if active_collection_id is not None and user is not None:
                st.divider()
                st.markdown("**Notes for this paper**")
                with session_scope() as session:
                    for n in notes_repo.list_for_paper(session, user_id=user.id, paper_id=paper["id"]):
                        st.caption(f"{n.created_at:%Y-%m-%d}: {n.content}")

                with session_scope() as session:
                    current = progress_repo.list_for_collection(
                        session, user_id=user.id, collection_id=active_collection_id
                    ).get(paper["id"])
                current_status = current.status if current else "not_started"
                statuses = ["not_started", "in_progress", "done"]
                new_status = st.selectbox(
                    "Reading progress", statuses, index=statuses.index(current_status),
                    format_func=lambda s: progress_repo.STATUS_LABELS[s],
                    key=f"status_{paper['id']}",
                )
                if new_status != current_status:
                    with session_scope() as session:
                        progress_repo.set_status(
                            session, user_id=user.id, paper_id=paper["id"],
                            status=new_status, collection_id=active_collection_id,
                        )
                    st.rerun()

                note_text = st.text_input("Add a note", key=f"ws_note_{paper['id']}", max_chars=20000)
                if st.button("Add note", key=f"ws_note_btn_{paper['id']}") and note_text.strip():
                    with session_scope() as session:
                        notes_repo.add_note(session, user_id=user.id, paper_id=paper["id"], content=note_text.strip())
                    st.rerun()

            if st.button("Close this item"):
                items.pop(idx)
                st.session_state["active_item"] = None
                st.rerun()

# --- Right panel: Collection ---
with right:
    with st.container(key="panel-tint-3"):
        st.markdown("##### Collection")

        if active_collection:
            with session_scope() as session:
                collection_papers = collections_repo.list_papers_in_collection(session, active_collection_id)
                for p in collection_papers:
                    c1, c2 = st.columns([5, 1])
                    has_summary = notes_repo.has_ai_summary(session, user_id=user.id, paper_id=p.id) if user else False
                    c1.write(p.title[:38] + (f" {notes_repo.AI_SUMMARY_LABEL}" if has_summary else ""))
                    if c2.button("📖", key=f"cread_{p.id}", help="Read"):
                        _open_item(_normalize_db_paper(p), "abstract")
                        st.rerun()
            if not collection_papers:
                st.caption("Nothing added yet — use the ⋮ menu on the left.")
        else:
            staged = st.session_state["staged_papers"]
            if not staged:
                st.caption("Add papers from the left panel.")
            for paper_id, paper in list(staged.items()):
                c1, c2 = st.columns([5, 1])
                label = paper["title"][:36] + (f" {notes_repo.AI_SUMMARY_LABEL}" if paper.get("_pending_summary") else "")
                c1.write(label)
                if c2.button("✕", key=f"unstage_{paper_id}"):
                    del st.session_state["staged_papers"][paper_id]
                    st.rerun()

            st.divider()
            collection_name = st.text_input(
                "Collection name", value=st.session_state.get("search_query", "New Collection").title(),
                max_chars=300,
            )

            existing_match = None
            merge_into_existing = False
            if user is not None and settings.has_db and collection_name.strip():
                with session_scope() as session:
                    existing_match = collections_repo.find_by_name(session, user_id=user.id, name=collection_name)
            if existing_match:
                merge_into_existing = st.checkbox(
                    f'You already have a collection named "{existing_match.name}" — '
                    "add these papers to it instead of creating a new one?",
                    value=True,
                )

            if st.button("Save Collection", type="primary", use_container_width=True, disabled=not staged):
                if user is None:
                    st.warning("Log in to save a collection.")
                    st.button("Log in", on_click=st.login, key="save_login")
                elif not settings.has_db:
                    st.error("No database configured — set DATABASE_URL or Lakebase variables in .env.")
                else:
                    try:
                        with session_scope() as session:
                            if existing_match and merge_into_existing:
                                collection = collections_repo.get_collection(session, existing_match.id)
                            else:
                                goal_id_raw = st.session_state.get("learning_goal_id")
                                collection = collections_repo.create_collection(
                                    session, user_id=user.id, name=collection_name,
                                    learning_goal_id=uuid.UUID(goal_id_raw) if goal_id_raw else None,
                                )
                            for paper in staged.values():
                                saved = papers_repo.upsert_paper(session, paper)
                                collections_repo.add_paper(session, collection_id=collection.id, paper_id=saved.id)
                                pending_summary = paper.get("_pending_summary")
                                if pending_summary:
                                    notes_repo.add_note(
                                        session, user_id=user.id, paper_id=saved.id,
                                        content=notes_repo.format_summary_note(pending_summary),
                                    )
                        st.session_state["staged_papers"] = {}
                        verb = "Added to" if (existing_match and merge_into_existing) else "Saved"
                        st.success(f"{verb} “{collection.name}” — {len(staged)} paper(s).")
                        st.page_link("pages/2_Profile.py", label="View in your profile")
                    except DatabaseNotConfigured as exc:
                        st.error(str(exc))

# --- Agent chat: compare/cite/recommend-next over this collection's papers ---
# Scoped to a loaded collection specifically — retrieve_evidence and recommend_next
# both need a concrete, bounded paper set to reason over, which "everything the user
# has ever searched for" isn't. This is the surface for 3 of the 6 tools in agent.py
# that otherwise have no UI: retrieve_evidence, generate_reading_plan, recommend_next.
# Same component Profile.py's collection detail view uses — see chat_ui.py.
if active_collection and user is not None:
    st.divider()
    chat_ui.render_agent_chat(active_collection_id, active_collection["name"], user)
