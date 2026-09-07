"""The sidebar: mission entry, pipeline stepper, run controls, connection panel."""

from __future__ import annotations

import re

import streamlit as st

from ..pipeline import STAGES, StageSpec
from ..runner import run_draft_pipeline
from ..state import MissionSession, StageStatus
from .common import rerun, toast
from .session import (
    active_stage_key,
    check_health,
    close_session,
    current_view,
    effective_settings,
    get_client,
    set_active_stage,
    set_override,
    set_view,
    start_session,
)

# Matches the sample mission IDs (26-IRB/AYVENS-019). Advisory only — an
# unrecognised format is a nudge, never a block, because the numbering scheme
# is the audit department's to change, not this app's.
_MISSION_PATTERN = re.compile(r"^\d{2}-[A-Z]{2,5}/[A-Z0-9]+-\d{2,4}$", re.IGNORECASE)


def render_sidebar() -> MissionSession | None:
    from .session import get_session

    with st.sidebar:
        st.markdown("### Mission preparation")
        st.caption("Internal Audit · AI pre-mission agent")

        session = get_session()
        if session is None:
            _mission_entry()
        else:
            _mission_header(session)
            _stepper(session)
            _run_controls(session)
            _navigation(session)
        st.divider()
        _connection_panel()
        return get_session()


# ---------------------------------------------------------------------------
# Mission entry
# ---------------------------------------------------------------------------


def _mission_entry() -> None:
    settings = effective_settings()
    mission_id = st.text_input(
        "Mission code",
        key="mission_code_input",
        placeholder="26-IRB/AYVENS-019",
        help="The mission reference from the audit plan. Everything else is derived from it.",
    ).strip()

    if mission_id and not _MISSION_PATTERN.match(mission_id):
        st.caption("⚠️ Unusual format — expected something like `26-IRB/AYVENS-019`.")

    if st.button(
        "Start preparation", type="primary", width="stretch", disabled=not mission_id
    ):
        start_session(mission_id)
        rerun()

    if settings.is_mock:
        from ..mock_backend import available_missions

        st.caption("Mock mode — bundled sample missions:")
        for sample_id, name in available_missions():
            if st.button(sample_id, key=f"sample_{sample_id}", width="stretch", help=name):
                start_session(sample_id)
                rerun()


def _mission_header(session: MissionSession) -> None:
    metadata = session.stage("mission_metadata").parsed()
    st.markdown(f"**{session.mission_id}**")
    name = getattr(metadata, "mission_name", None)
    if name:
        st.caption(name)
    done = session.approved_count
    st.progress(done / len(STAGES), text=f"{done} of {len(STAGES)} stages approved")


# ---------------------------------------------------------------------------
# Stepper
# ---------------------------------------------------------------------------


def _stepper(session: MissionSession) -> None:
    st.markdown("###### Pipeline")
    active = active_stage_key()
    view = current_view()
    for spec in STAGES:
        run = session.stage(spec.key)
        icon = "◆" if run.stale else run.status.icon
        is_active = view == "stage" and spec.key == active
        if st.button(
            f"{icon}  {spec.number}. {spec.short_label}",
            key=f"nav_{spec.key}",
            width="stretch",
            type="primary" if is_active else "secondary",
            help=_stage_help(session, spec),
        ):
            set_active_stage(spec.key)
            rerun()


def _stage_help(session: MissionSession, spec: StageSpec) -> str:
    run = session.stage(spec.key)
    if run.stale:
        return "Stale — an upstream stage changed after this ran"
    blocking = session.blocking_reason(spec)
    if run.status is StageStatus.PENDING and blocking:
        return blocking
    return f"{run.status.label}{' · edited' if run.edited else ''}"


# ---------------------------------------------------------------------------
# Run controls & navigation
# ---------------------------------------------------------------------------


def _run_controls(session: MissionSession) -> None:
    st.markdown("###### Run")
    actionable = session.next_actionable()
    if actionable is not None and st.button(
        f"Go to {actionable.short_label}", width="stretch", help=actionable.purpose
    ):
        set_active_stage(actionable.key)
        rerun()

    if st.button(
        "Draft run (all remaining)",
        width="stretch",
        help=(
            "Runs every outstanding stage back to back and leaves all of them awaiting your "
            "review. Nothing is auto-approved."
        ),
    ):
        _draft_run(session)

    if st.button("Close mission", width="stretch", help="Clear this session"):
        close_session()
        rerun()


def _draft_run(session: MissionSession) -> None:
    client = get_client()
    status_box = st.empty()

    def on_progress(spec: StageSpec) -> None:
        status_box.caption(f"Running {spec.short_label}…")

    with st.spinner("Draft run in progress…"):
        completed = run_draft_pipeline(session, client, on_progress=on_progress)
    status_box.empty()

    if completed:
        toast(f"{len(completed)} stage(s) ready for review", icon="📋")
        first = session.next_actionable()
        if first:
            set_active_stage(first.key)
    else:
        toast("Nothing left to run", icon="ℹ️")
    rerun()


def _navigation(session: MissionSession) -> None:
    st.markdown("###### Output")
    view = current_view()
    if st.button(
        "Briefing pack",
        width="stretch",
        type="primary" if view == "briefing_pack" else "secondary",
        help="The assembled document and its exports",
    ):
        set_view("briefing_pack")
        rerun()
    if st.button(
        f"Audit trail ({len(session.audit_trail)})",
        width="stretch",
        type="primary" if view == "audit_trail" else "secondary",
        help="Every agent run and every analyst change, in order",
    ):
        set_view("audit_trail")
        rerun()


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def _connection_panel() -> None:
    settings = effective_settings()
    label = "Mock backend" if settings.is_mock else "Live backend"
    with st.expander(f"Connection — {label}", expanded=False):
        mode = st.radio(
            "Backend",
            ["mock", "live"],
            index=0 if settings.is_mock else 1,
            horizontal=True,
            key="backend_mode_radio",
            help="Mock runs offline against bundled sample missions.",
        )
        if mode != settings.backend_mode:
            set_override("backend_mode", mode)
            rerun()

        if mode == "live":
            base_url = st.text_input(
                "Base URL", value=settings.base_url, placeholder="https://audit-agent.internal"
            ).strip()
            if base_url != settings.base_url:
                set_override("base_url", base_url)
                rerun()
            st.caption(f"Stage endpoint: `{settings.stage_path}`")

        health = check_health()
        if health.ok:
            latency = f" · {health.latency_ms:.0f} ms" if health.latency_ms else ""
            st.success(f"{health.detail}{latency}", icon="✅")
        else:
            st.error(health.detail, icon="🚨")

        if st.button("Re-check", width="stretch"):
            check_health(force=True)
            rerun()

        st.caption(f"Analyst: `{settings.analyst}`")
