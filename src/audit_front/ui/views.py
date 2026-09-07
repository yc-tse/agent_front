"""Non-stage views: the landing page, the briefing pack, and the audit trail."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..exporters import export_filename, session_to_json, session_to_markdown
from ..pipeline import STAGES, get_stage
from ..state import MissionSession, StageStatus
from .common import hero, rerun, section, status_chip
from .session import effective_settings, set_active_stage

# ---------------------------------------------------------------------------
# Landing
# ---------------------------------------------------------------------------


def render_welcome() -> None:
    settings = effective_settings()
    hero(
        "Pre-mission preparation",
        "Enter a mission code in the sidebar to start. The agent runs six stages; you review "
        "and approve each one before it feeds the next.",
    )

    st.markdown("##### What the agent does, and where you come in")
    for spec in STAGES:
        with st.container(border=True):
            left, right = st.columns([0.32, 0.68])
            with left:
                st.markdown(f"**{spec.title}**")
                st.caption(spec.short_label)
            with right:
                st.markdown(spec.purpose)
                st.caption(f"Your checkpoint — {spec.hitl_note}")

    if settings.is_mock:
        st.info(
            "Running in **mock mode**: the six stages are served from bundled sample missions, "
            "with no network calls. Point `AUDIT_API_BASE_URL` at the backend and set "
            "`AUDIT_BACKEND_MODE=live` to use the real agent.",
            icon="🧪",
        )


# ---------------------------------------------------------------------------
# Briefing pack
# ---------------------------------------------------------------------------


def render_briefing_pack(session: MissionSession) -> None:
    hero(
        "Briefing pack",
        f"{session.mission_id} · {session.approved_count} of {len(STAGES)} stages approved",
    )

    outstanding = [
        spec for spec in STAGES if session.stage(spec.key).status is not StageStatus.APPROVED
    ]
    if outstanding:
        st.warning(
            "Not every stage is approved yet. The pack below exports what exists today; "
            "unapproved stages are labelled as such.",
            icon="⚠️",
        )
        columns = st.columns(min(3, len(outstanding)))
        for column, spec in zip(columns, outstanding[:3], strict=False):
            with column:
                if st.button(
                    f"Go to {spec.short_label}",
                    key=f"pack_go_{spec.key}",
                    width="stretch",
                ):
                    set_active_stage(spec.key)
                    rerun()

    if session.stale_stages:
        stale = ", ".join(get_stage(k).short_label for k in session.stale_stages)
        st.error(f"Stale stages — re-run before circulating: {stale}", icon="🚨")

    section("Stage status")
    status_columns = st.columns(len(STAGES))
    for column, spec in zip(status_columns, STAGES, strict=False):
        run = session.stage(spec.key)
        with column:
            st.caption(f"{spec.number}. {spec.short_label}")
            st.markdown(
                status_chip(run.status, stale=run.stale, edited=run.edited),
                unsafe_allow_html=True,
            )

    st.divider()
    scope_choice = st.radio(
        "Contents",
        ["Full pack (all six stages)", "Briefing only"],
        horizontal=True,
        key="pack_scope",
    )
    include_all = scope_choice.startswith("Full")
    markdown = session_to_markdown(session, include_all_stages=include_all)

    download_md, download_json = st.columns(2)
    with download_md:
        st.download_button(
            "Download Markdown",
            data=markdown,
            file_name=export_filename(session, "md"),
            mime="text/markdown",
            width="stretch",
            type="primary",
        )
    with download_json:
        st.download_button(
            "Download full record (JSON)",
            data=session_to_json(session),
            file_name=export_filename(session, "json"),
            mime="application/json",
            width="stretch",
            help=(
                "Agent output, your overrides and the audit trail — the defensible record of "
                "how this pack was produced."
            ),
        )

    document, raw = st.tabs(["Document", "Markdown source"])
    with document:
        st.markdown(markdown)
    with raw:
        st.code(markdown, language="markdown")


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


def render_audit_trail(session: MissionSession) -> None:
    hero(
        "Audit trail",
        "Every agent run and every analyst change, in order. This is what makes the "
        "AI-assisted deliverable defensible.",
    )

    edited = [get_stage(k).short_label for k in session.stages if session.stage(k).edited]
    metrics = st.columns(4)
    metrics[0].metric("Recorded events", len(session.audit_trail))
    metrics[1].metric("Stages approved", f"{session.approved_count}/{len(STAGES)}")
    metrics[2].metric("Stages you amended", len(edited))
    metrics[3].metric("Stale stages", len(session.stale_stages))

    if edited:
        st.caption("Amended by you: " + ", ".join(edited))

    if not session.audit_trail:
        st.caption("Nothing recorded yet.")
        return

    frame = pd.DataFrame(
        [
            {
                "Time (UTC)": event.timestamp.strftime("%H:%M:%S"),
                "Actor": event.actor,
                "Action": event.action.replace("_", " "),
                "Stage": get_stage(event.stage).short_label if event.stage else "—",
                "Detail": event.detail or "",
            }
            for event in session.audit_trail
        ]
    )
    st.dataframe(frame, width="stretch", hide_index=True)

    st.download_button(
        "Download the full record (JSON)",
        data=session_to_json(session),
        file_name=export_filename(session, "json"),
        mime="application/json",
    )
