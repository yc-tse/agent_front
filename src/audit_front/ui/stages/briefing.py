"""Stage 6 — consolidated pre-mission briefing.

The deliverable. Editing here is expected rather than exceptional, so the
editors are richer and a live markdown preview sits next to them.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ...exporters import briefing_markdown, export_filename, stage_markdown
from ...models import Briefing
from ...state import MissionSession, StageRun
from ..common import bullets, empty_state, section, tags, unmodelled_fields
from ..hitl import list_editor, text_editor

_MAX_AXES = 8


def _render_axes(model: Briefing) -> None:
    for index, axis in enumerate(model.thematic_axes, start=1):
        st.markdown(f"**{index}. {axis.title or 'Axis'}**")
        bullets(axis.points)


def render(session: MissionSession, run: StageRun) -> dict[str, Any]:
    model: Briefing = run.parsed()

    stale = session.stale_stages
    if stale:
        st.warning(
            "An upstream stage changed after this briefing was generated. Re-run it so the "
            "briefing reflects the perimeter you approved.",
            icon="⚠️",
        )

    if not any([model.objective, model.thematic_axes, model.perimeter, model.markdown]):
        empty_state(
            "The briefing came back empty",
            "No objective, perimeter or thematic axis was returned. Re-run the stage, or write "
            "the briefing yourself in the editor below — the export will carry your version.",
        )

    if model.objective:
        section("Mission objective (operational view)")
        st.markdown(model.objective)

    if model.perimeter:
        section("Perimeter to use for all pre-mission work")
        tags(model.perimeter)

    if model.thematic_axes:
        section("Key thematic axes to prepare for")
        _render_axes(model)

    columns = st.columns(2)
    with columns[0]:
        section("Risk landscape for preparation")
        bullets(model.risk_landscape)
        section("Methodology stance")
        bullets(model.methodology_stance)
    with columns[1]:
        section("Historical context")
        bullets(model.historical_context)
        section("Open questions for the opening meeting")
        bullets(model.open_questions, empty="None recorded — add any before the kick-off.")

    if model.markdown and not model.objective:
        st.markdown(model.markdown)

    unmodelled_fields(model)

    st.download_button(
        "Download this briefing (Markdown)",
        data=stage_markdown(run),
        file_name=export_filename(session, "md"),
        mime="text/markdown",
        key="dl_briefing_only",
    )

    # -- human-in-the-loop -------------------------------------------------
    draft = dict(run.payload)
    with st.expander("Edit the briefing", expanded=False):
        st.caption(
            "Treat this as your document. The agent's original stays in the audit trail and in "
            "the JSON export."
        )
        edit_tab, preview_tab = st.tabs(["Edit", "Preview"])

        with edit_tab:
            draft["objective"] = text_editor(
                "Mission objective", model.objective, key=f"{run.key}_objective", height=110
            )
            draft["perimeter"] = list_editor(
                "Perimeter", model.perimeter, key=f"{run.key}_perimeter"
            )

            st.markdown("**Thematic axes**")
            axis_count = st.number_input(
                "Number of axes",
                min_value=0,
                max_value=_MAX_AXES,
                value=min(len(model.thematic_axes), _MAX_AXES),
                key=f"hitl_{run.key}_axis_count",
                help="Increase to add an axis the agent missed.",
            )
            axes: list[dict[str, Any]] = []
            for index in range(int(axis_count)):
                source = model.thematic_axes[index] if index < len(model.thematic_axes) else None
                with st.container(border=True):
                    title = st.text_input(
                        f"Axis {index + 1} title",
                        value=source.title if source else "",
                        key=f"hitl_{run.key}_axis_{index}_title",
                    ).strip()
                    points = list_editor(
                        f"Axis {index + 1} points",
                        source.points if source else [],
                        key=f"{run.key}_axis_{index}_points",
                    )
                if title or points:
                    axes.append({"title": title, "points": points})
            draft["thematic_axes"] = axes

            col_a, col_b = st.columns(2)
            with col_a:
                draft["risk_landscape"] = list_editor(
                    "Risk landscape", model.risk_landscape, key=f"{run.key}_risk"
                )
                draft["methodology_stance"] = list_editor(
                    "Methodology stance", model.methodology_stance, key=f"{run.key}_method"
                )
            with col_b:
                draft["historical_context"] = list_editor(
                    "Historical context", model.historical_context, key=f"{run.key}_history"
                )
                draft["open_questions"] = list_editor(
                    "Open questions",
                    model.open_questions,
                    key=f"{run.key}_questions",
                    help_text="What you still need from the auditee before the opening meeting.",
                )

        with preview_tab:
            st.caption("How your edited briefing will export.")
            preview = briefing_markdown(Briefing.model_validate(draft))
            st.markdown(preview or "_Nothing to preview yet._")

    return draft
