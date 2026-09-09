"""Stage views and the frame they all share.

Each stage module exposes ``render(session, run) -> dict`` which draws the
stage's content plus its editors and returns the *draft payload* — the payload
as the analyst has it on screen right now. The frame here owns everything the
stage views have in common: the header, the run/retry states, the review bar and
the raw-payload escape hatch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from ...pipeline import StageSpec, get_stage
from ...runner import run_stage
from ...state import MissionSession, StageStatus
from ..common import (
    hero,
    hitl_note,
    meta_line,
    purpose,
    raw_payload,
    rerun,
    source_chip,
    status_chip,
    warnings_block,
)
from ..hitl import review_bar
from . import (
    briefing,
    methodology,
    mission_metadata,
    recommendations,
    reports,
    risk_events,
    scope,
)

Renderer = Callable[[MissionSession, Any], dict[str, Any]]

RENDERERS: dict[str, Renderer] = {
    "mission_metadata": mission_metadata.render,
    "scope_understanding": scope.render,
    "risk_events": risk_events.render,
    "methodology": methodology.render,
    "historical_reports": reports.render,
    "historical_recommendations": recommendations.render,
    "briefing": briefing.render,
}

__all__ = ["RENDERERS", "render_stage"]


def render_stage(session: MissionSession, spec: StageSpec, client: Any) -> None:
    """Draw one pipeline stage, whatever state it is in."""
    run = session.stage(spec.key)

    chips = status_chip(run.status, stale=run.stale, edited=run.edited)
    if run.has_result and (source := source_chip(run.source)):
        chips += f'<span style="margin-left:.4rem;">{source}</span>'
    if spec.critical_checkpoint:
        chips += (
            '<span class="af-chip" style="color:#B06000;background:#FFF4E5;margin-left:.4rem;">'
            "critical checkpoint</span>"
        )
    hero(spec.title, spec.purpose if not run.has_result else "", chips_html=chips)

    if run.has_result:
        purpose(spec.purpose)
    meta_line(run)

    blocking = session.blocking_reason(spec)

    if run.stale:
        st.warning(
            "An upstream stage changed after this ran, so what you see below is out of date. "
            "Re-run the stage to bring it back in line with the approved perimeter.",
            icon="⚠️",
        )
        if st.button(
            "Re-run with the current perimeter",
            type="primary",
            key=f"restale_{spec.key}",
        ):
            _execute(session, client, spec)

    if run.status is StageStatus.ERROR:
        st.error(run.error or "The stage failed.", icon="🚨")
        retry, skip = st.columns([0.3, 0.7])
        with retry:
            if st.button("Try again", type="primary", key=f"retry_{spec.key}"):
                _execute(session, client, spec)
        with skip:
            st.caption(
                "If the backend is unreachable, check the connection panel in the sidebar. "
                "Mock mode lets you keep working on the rest of the pipeline."
            )

    if not run.has_result:
        hitl_note(spec.hitl_note)
        if blocking:
            st.info(blocking, icon="🔒")
            _dependency_list(session, spec)
        else:
            st.caption(_context_summary(session, spec))
            if st.button(
                f"Run {spec.label.lower()}",
                type="primary",
                key=f"run_{spec.key}",
                disabled=run.status is StageStatus.RUNNING,
            ):
                _execute(session, client, spec)
        return

    warnings_block(run)
    if run.status is not StageStatus.APPROVED:
        hitl_note(spec.hitl_note)
    if run.feedback:
        st.caption(f"Last re-run instruction: _{run.feedback}_")

    renderer = RENDERERS.get(spec.key)
    draft = renderer(session, run) if renderer else None

    review_bar(session, spec, client, draft=draft)
    raw_payload(run)


def _execute(session: MissionSession, client: Any, spec: StageSpec) -> None:
    with st.spinner(f"Running {spec.label.lower()}…"):
        run_stage(session, client, spec)
    rerun()


def _dependency_list(session: MissionSession, spec: StageSpec) -> None:
    st.caption("This stage runs on the output you approved in:")
    for dep in spec.depends_on:
        dep_spec = get_stage(dep)
        dep_run = session.stage(dep)
        st.markdown(
            f"- {dep_spec.title} — {status_chip(dep_run.status, stale=dep_run.stale)}",
            unsafe_allow_html=True,
        )


def _context_summary(session: MissionSession, spec: StageSpec) -> str:
    """Tell the analyst exactly what will be sent, before they press Run."""
    if not spec.depends_on:
        return f"Will query the backend for mission {session.mission_id}."
    parts: list[str] = []
    scope_run = session.stage("scope_understanding")
    if "scope_understanding" in spec.depends_on and scope_run.has_result:
        model = scope_run.parsed()
        filters = [
            f"{len(values)} {name}"
            for name, values in (
                ("entities", model.entity_filter),
                ("risk families", model.risk_filter),
                ("activities", model.activity_filter),
                ("countries", model.country_filter),
            )
            if values
        ]
        parts.append("perimeter: " + (", ".join(filters) if filters else "unfiltered"))
    names = ", ".join(get_stage(dep).short_label for dep in spec.depends_on)
    parts.append(f"context from {names}")
    return "Will run with " + " · ".join(parts) + "."
