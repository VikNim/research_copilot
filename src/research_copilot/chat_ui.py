"""Agent chat panel — one collection's conversation, rendered identically
wherever a collection is on screen (Workspace's loaded-collection mode,
Profile's collection detail). Pulled out of Workspace.py so both pages call
the same implementation instead of drifting apart.

History lives in st.session_state["agent_chats"][str(collection_id)], so it
carries over between the two pages for the same collection, and across a
fresh unrelated search — only the tab-state a new search actually invalidates
(open_items, staged_papers) gets cleared, not chat history tied to a
collection the user may return to.
"""

from __future__ import annotations

import uuid

import streamlit as st

from research_copilot import agent
from research_copilot.config import get_settings
from research_copilot.db import session_scope
from research_copilot.llm import LLMNotConfigured
from research_copilot.models import User

# Shown only on an empty conversation (once there's real history, suggestions
# would just crowd the messages) — one per tool the agent actually has, so
# each suggestion demonstrably does something rather than being a generic
# icebreaker.
SUGGESTED_PROMPTS = [
    "Generate a reading plan for these papers",
    "Where should I start reading?",
    "Compare these papers for me",
    "What are the key takeaways across these papers?",
    "Find more papers on this topic",
]


def render_agent_chat(collection_id: uuid.UUID, collection_name: str, user: User) -> None:
    settings = get_settings()
    st.markdown(f"##### Ask the agent about “{collection_name}”")
    if not settings.has_chat_llm:
        st.info("The agent needs a chat LLM configured (Databricks FM API or the chat proxy) to hold a conversation.")
        return

    chat_key = str(collection_id)
    chats = st.session_state.setdefault("agent_chats", {})
    chat_history = chats.setdefault(chat_key, [])

    for msg in chat_history:
        role = msg.get("role")
        if role == "user":
            with st.chat_message("user"):
                st.write(msg.get("content", ""))
        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                names = ", ".join(tc["function"]["name"] for tc in tool_calls)
                st.caption(f"\U0001f527 checked: {names}")
            if msg.get("content"):
                with st.chat_message("assistant"):
                    st.write(msg["content"])
        # role == "tool": raw tool output, not shown — the caption above already
        # says what was used, and the assistant's next message cites what it found.

    prompt = None
    if not chat_history:
        st.caption("Try asking:")
        cols = st.columns(len(SUGGESTED_PROMPTS))
        for col, suggestion in zip(cols, SUGGESTED_PROMPTS):
            if col.button(suggestion, key=f"suggest_{chat_key}_{suggestion}", use_container_width=True):
                prompt = suggestion

    typed = st.chat_input(
        "Ask it to compare papers, cite evidence, or say what to read next...",
        key=f"agent_chat_input_{chat_key}",
    )
    prompt = prompt or typed
    if prompt:
        with st.spinner("Thinking..."):
            try:
                with session_scope() as session:
                    chats[chat_key] = agent.run_agent(
                        session,
                        user.id,
                        prompt,
                        history=chat_history,
                        context_note=(
                            f'The active collection_id is "{collection_id}" '
                            f'(name: "{collection_name}"). Use it for any tool '
                            "that takes a collection_id unless the user names a different one."
                        ),
                    )
            except LLMNotConfigured as exc:
                st.error(str(exc))
        st.rerun()
