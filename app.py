"""Entry point for the mission-preparation front-end.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `streamlit run app.py` straight from a clone, without installing the
# package first. An installed copy resolves the same imports from site-packages.
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import streamlit as st  # noqa: E402

from audit_front.pipeline import get_stage  # noqa: E402
from audit_front.ui.common import inject_css  # noqa: E402
from audit_front.ui.session import active_stage_key, current_view, get_client  # noqa: E402
from audit_front.ui.sidebar import render_sidebar  # noqa: E402
from audit_front.ui.stages import render_stage  # noqa: E402
from audit_front.ui.views import (  # noqa: E402
    render_audit_trail,
    render_briefing_pack,
    render_welcome,
)

st.set_page_config(
    page_title="Audit mission preparation",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    inject_css()
    session = render_sidebar()

    if session is None:
        render_welcome()
        return

    view = current_view()
    if view == "briefing_pack":
        render_briefing_pack(session)
    elif view == "audit_trail":
        render_audit_trail(session)
    else:
        render_stage(session, get_stage(active_stage_key()), get_client())


main()
