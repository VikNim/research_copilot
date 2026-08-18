"""Per-session light/dark mode + panel backgrounds.

Implemented as injected CSS driven by st.session_state, not Streamlit's native
`[theme]` config in config.toml — that setting is server-wide, so flipping it
at runtime would change the theme for every logged-in user's session at once,
not just the one who clicked the toggle. This keeps the toggle scoped to the
browser session that clicked it, same as everything else in st.session_state.

Panels use one hue (the app's teal primary color) at four lightness steps,
not four unrelated colors — enough to tell panels apart without looking like
a rainbow.

Two building blocks pages use:
- `st.container(key="panel-tint-<1-4>")` around a whole panel's content,
  styled here via the `.st-key-panel-tint-<n>` class Streamlit generates
  from `key=`.
- `st.container(border=True, key=f"card-<label>-<id>")` around one card,
  styled here via an `[class*="st-key-card-"]` substring match so every card
  gets the same treatment without a fixed key per page.
"""

from __future__ import annotations

import streamlit as st

_LIGHT = {
    "app_bg": "#F7F9FC",
    "sidebar_bg": "#FFFFFF",
    "text": "#1F2933",
    "muted_text": "#5B6B79",
    "border": "#D8E1E8",
    "primary": "#1F5C6B",
    "primary_hover": "#164753",
    "primary_text": "#FFFFFF",
    "input_bg": "#FFFFFF",
    "card_bg": "rgba(255, 255, 255, 0.75)",
    "card_border": "rgba(31, 41, 51, 0.12)",
    "header_text": "#2C4A54",  # subtle dark teal — legible, not black
    "shadow_sm": "0 1px 2px rgba(23, 43, 51, 0.06)",
    "shadow_md": "0 8px 24px rgba(23, 43, 51, 0.10)",
    "shadow_focus": "0 0 0 3px rgba(31, 92, 107, 0.18)",
    # One hue (teal, matches primaryColor), four lightness steps.
    "panel_tint_1_bg": "#EAF4F5", "panel_tint_1_border": "#BFE0E3",
    "panel_tint_2_bg": "#DCEEF0", "panel_tint_2_border": "#A7D6DA",
    "panel_tint_3_bg": "#CDE6E9", "panel_tint_3_border": "#8FC9CF",
    "panel_tint_4_bg": "#BEDEE2", "panel_tint_4_border": "#78BCC3",
}

_DARK = {
    "app_bg": "#10151C",
    "sidebar_bg": "#161C25",
    "text": "#E7EDF3",
    "muted_text": "#9AA9B6",
    "border": "#2A333D",
    "primary": "#4FB4CC",
    "primary_hover": "#6FC7DC",
    "primary_text": "#0B1116",
    "input_bg": "#1B2229",
    "card_bg": "rgba(255, 255, 255, 0.05)",
    "card_border": "rgba(255, 255, 255, 0.12)",
    "header_text": "#A9CDD3",  # light teal — legible on dark, not stark white
    "shadow_sm": "0 1px 2px rgba(0, 0, 0, 0.35)",
    "shadow_md": "0 10px 28px rgba(0, 0, 0, 0.45)",
    "shadow_focus": "0 0 0 3px rgba(79, 180, 204, 0.25)",
    # Same hue, deepened rather than blackened, same four steps.
    "panel_tint_1_bg": "#172A30", "panel_tint_1_border": "#234049",
    "panel_tint_2_bg": "#1D3239", "panel_tint_2_border": "#2C4A54",
    "panel_tint_3_bg": "#23393F", "panel_tint_3_border": "#34535E",
    "panel_tint_4_bg": "#294249", "panel_tint_4_border": "#3C5C68",
}


def is_dark() -> bool:
    return bool(st.session_state.get("dark_mode", False))


def theme_toggle_button(key: str) -> None:
    """A small icon button that flips dark_mode and reruns. Give each call
    site its own `key` — the header renders on every page."""
    dark = is_dark()
    if st.button("☀️" if dark else "🌙", key=key, help="Toggle light/dark mode"):
        st.session_state["dark_mode"] = not dark
        st.rerun()


def header_text_color() -> str:
    return (_DARK if is_dark() else _LIGHT)["header_text"]


def apply_theme() -> None:
    """Call once near the top of every page, after st.set_page_config."""
    t = _DARK if is_dark() else _LIGHT
    st.markdown(
        f"""
<style>
:root {{ color-scheme: {"dark" if is_dark() else "light"}; }}

[data-testid="stAppViewContainer"], [data-testid="stMain"], .stApp {{
    background-color: {t['app_bg']};
}}
[data-testid="stHeader"] {{ background-color: transparent; }}
[data-testid="stSidebar"] {{
    background-color: {t['sidebar_bg']};
    border-right: 1px solid {t['border']};
}}

[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
h1, h2, h3, h4, h5, h6, label, [data-testid="stWidgetLabel"] p {{
    color: {t['text']};
}}
h1, h2, h3, h4, h5, h6 {{ letter-spacing: -0.01em; font-weight: 650; }}
[data-testid="stCaptionContainer"] {{ color: {t['muted_text']} !important; }}

/* --- Buttons: a resting shadow, a lift + brighten on hover, a press-down on click --- */
.stButton > button, [data-testid^="stBaseButton"] {{
    background-color: {t['input_bg']};
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    box-shadow: {t['shadow_sm']};
    transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease, background-color 0.15s ease;
}}
.stButton > button:hover, [data-testid^="stBaseButton"]:hover {{
    border-color: {t['primary']};
    box-shadow: {t['shadow_md']};
    transform: translateY(-1px);
}}
.stButton > button:active, [data-testid^="stBaseButton"]:active {{
    transform: translateY(0);
    box-shadow: {t['shadow_sm']};
}}
.stButton > button:focus-visible, [data-testid^="stBaseButton"]:focus-visible {{
    outline: none;
    box-shadow: {t['shadow_focus']};
}}
[data-testid="stBaseButton-primary"] {{
    background-color: {t['primary']} !important;
    color: {t['primary_text']} !important;
    border: none !important;
}}
[data-testid="stBaseButton-primary"]:hover {{
    background-color: {t['primary_hover']} !important;
}}
/* The selected segment in a segmented_control — whichever aria attribute this
   Streamlit version marks it with, give it real contrast so "which tab am I
   on" reads at a glance instead of blending into the unselected segments. */
[data-testid^="stBaseButton"][aria-checked="true"],
[data-testid^="stBaseButton"][aria-pressed="true"],
[data-testid^="stBaseButton"][aria-selected="true"] {{
    background-color: {t['primary']} !important;
    color: {t['primary_text']} !important;
    border-color: {t['primary']} !important;
}}

[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stChatInput"] textarea {{
    background-color: {t['input_bg']} !important;
    color: {t['text']} !important;
    border-color: {t['border']} !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus,
[data-testid="stChatInput"] textarea:focus {{
    border-color: {t['primary']} !important;
    box-shadow: {t['shadow_focus']} !important;
}}

[data-testid="stExpander"], [data-testid="stPopoverBody"], [data-testid="stChatMessage"] {{
    background-color: {t['card_bg']};
    border: 1px solid {t['card_border']};
    border-radius: 10px;
    box-shadow: {t['shadow_sm']};
}}

hr {{ border-color: {t['border']}; }}

/* Panels — wrap a whole panel's content with st.container(key="panel-tint-<n>") */
.st-key-panel-tint-1, .st-key-panel-tint-2, .st-key-panel-tint-3, .st-key-panel-tint-4 {{
    border-radius: 14px; padding: 1rem; box-shadow: {t['shadow_sm']};
    transition: box-shadow 0.2s ease;
}}
.st-key-panel-tint-1 {{ background: {t['panel_tint_1_bg']}; border: 1px solid {t['panel_tint_1_border']}; }}
.st-key-panel-tint-2 {{ background: {t['panel_tint_2_bg']}; border: 1px solid {t['panel_tint_2_border']}; }}
.st-key-panel-tint-3 {{ background: {t['panel_tint_3_bg']}; border: 1px solid {t['panel_tint_3_border']}; }}
.st-key-panel-tint-4 {{ background: {t['panel_tint_4_bg']}; border: 1px solid {t['panel_tint_4_border']}; }}

/* Cards inside panels — wrap one card with st.container(border=True, key=f"card-...") */
[class*="st-key-card-"] {{
    background-color: {t['card_bg']} !important;
    border-color: {t['card_border']} !important;
    border-radius: 10px !important;
    box-shadow: {t['shadow_sm']};
    transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}}
[class*="st-key-card-"]:hover {{
    box-shadow: {t['shadow_md']};
    border-color: {t['primary']} !important;
    transform: translateY(-2px);
}}

@media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{ transition: none !important; animation: none !important; }}
}}
</style>
""",
        unsafe_allow_html=True,
    )
