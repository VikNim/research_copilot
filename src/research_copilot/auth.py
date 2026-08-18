"""Google sign-in via Streamlit's native OIDC support (st.login/st.user/st.logout).
Needs streamlit>=1.42 and an [auth] block in .streamlit/secrets.toml — see
.streamlit/secrets.toml.example. UNVERIFIED against a real Google OAuth app; none
is registered yet (infra starts from zero, see project memory).

"Log in" and "Sign up" are the same underlying action (st.login()) — Google's
account chooser handles both new and returning accounts in one OIDC flow.
"""

from __future__ import annotations

import streamlit as st

from research_copilot import theme
from research_copilot.db import session_scope
from research_copilot.models import User
from research_copilot.repositories.users import upsert_user


def current_user() -> User | None:
    """Returns the app's User row for the logged-in Google identity, upserting on
    first sight. Returns None if nobody is logged in."""
    if not getattr(st.user, "is_logged_in", False):
        return None
    with session_scope() as session:
        user = upsert_user(
            session,
            google_sub=st.user.get("sub"),
            email=st.user.get("email"),
            display_name=st.user.get("name"),
            avatar_url=st.user.get("picture"),
        )
        session.expunge(user)
        return user


def _centered_title(site_name: str) -> None:
    st.markdown(
        f"<h1 style='text-align:center; color:{theme.header_text_color()}; "
        "margin:0.25rem 0 0.75rem 0; text-wrap:balance;'>"
        f"\U0001f9ed&nbsp;&nbsp;{site_name}</h1>",
        unsafe_allow_html=True,
    )


def render_header(site_name: str, show_auth_buttons: bool = True) -> User | None:
    """Renders the auth-buttons row + centered site title used on Screens 1 and 2.
    Returns the current user (or None) so the caller can branch on it."""
    user = current_user()
    spacer, right, toggle_col = st.columns([3, 1, 0.4])
    with right:
        if user is None and show_auth_buttons:
            b1, b2 = st.columns(2)
            b1.button("Log in", on_click=st.login, use_container_width=True)
            b2.button("Sign up", on_click=st.login, use_container_width=True)
        elif user is not None:
            st.button(f"Log out ({user.display_name or user.email})", on_click=st.logout)
    with toggle_col:
        theme.theme_toggle_button(key="theme_toggle_header")
    _centered_title(site_name)
    return user


def require_login(site_name: str) -> User:
    """Route guard for Screen 3 (User Profile page) — no auth buttons shown here;
    an unauthenticated visitor is redirected back to the landing page instead."""
    user = current_user()
    spacer, toggle_col = st.columns([4, 0.4])
    with toggle_col:
        theme.theme_toggle_button(key="theme_toggle_require_login")
    _centered_title(site_name)
    if user is None:
        st.info("Log in to see your collections.")
        st.button("Log in", on_click=st.login)
        st.stop()
    return user
