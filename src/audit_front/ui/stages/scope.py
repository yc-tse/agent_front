"""Stage 2 — mission scope understanding.

The critical checkpoint. Everything downstream is filtered by what leaves this
page, so the view leads with the difference between the reference perimeter
and the perimeter the agent proposed.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ...models import MissionMetadata, ScopeUnderstanding
from ...state import MissionSession, StageRun
from ..common import bullets, field_row, section, tags, unmodelled_fields
from ..hitl import choice_editor, list_editor, selection_editor, text_editor

_DRIVERS = [
    "Entity-driven",
    "Country-driven",
    "Process-driven",
    "Risk-driven",
    "Regulation-driven",
    "Business-line-driven",
]
_COVERAGE = ["Exact", "Approximate", "Partial", "Uncertain"]

_FILTERS: tuple[tuple[str, str], ...] = (
    ("entity_filter", "Entity filter"),
    ("country_filter", "Country filter"),
    ("risk_filter", "Risk filter"),
    ("activity_filter", "Activity filter"),
    ("business_line_filter", "Business line filter"),
)


def _perimeter_delta(model: ScopeUnderstanding, metadata: MissionMetadata) -> None:
    """Say plainly how the proposed filter compares to the reference entity list."""
    reference = set(metadata.entities)
    proposed = set(model.entity_filter)
    if not reference and not proposed:
        return

    dropped = sorted(reference - proposed)
    added = sorted(proposed - reference)

    if not dropped and not added and reference:
        st.success(
            f"The entity filter matches all {len(reference)} entities from the mission metadata.",
            icon="✅",
        )
        return
    if dropped:
        st.warning(
            f"{len(dropped)} entity/entities from the metadata are **not** in the filter: "
            + ", ".join(dropped),
            icon="⚠️",
        )
    if added:
        st.info(
            f"{len(added)} entity/entities in the filter are not in the mission metadata: "
            + ", ".join(added),
            icon="ℹ️",
        )


def render(session: MissionSession, run: StageRun) -> dict[str, Any]:
    model: ScopeUnderstanding = run.parsed()
    metadata: MissionMetadata = session.stage("mission_metadata").parsed()

    active_filters = [(key, label) for key, label in _FILTERS if getattr(model, key)]

    field_row(
        [
            ("Primary scope driver", model.primary_scope_driver),
            ("Scope coverage", model.scope_coverage),
            ("Active filter dimensions", len(active_filters) or None),
        ]
    )

    if model.is_empty:
        st.error(
            "No filter dimension is set. Every downstream stage would run against the whole "
            "population. Set at least one filter before approving.",
            icon="🚨",
        )
    else:
        _perimeter_delta(model, metadata)

    if model.brief_scope:
        st.markdown(f"> {model.brief_scope}")

    section(
        "Scope definition used for filtering",
        help_text="Exactly what the risk-event, methodology and recommendation searches receive.",
    )
    if active_filters:
        for key, label in active_filters:
            values: list[str] = getattr(model, key)
            st.markdown(f"**{label}** — {len(values)} value(s)")
            tags(values)
    else:
        st.caption("No filters defined.")

    left, right = st.columns([0.55, 0.45])
    with left:
        section("Reasoning")
        bullets(model.reasoning, empty="The agent gave no rationale for this scoping.")
    with right:
        section("Missing dimensions")
        if model.missing_dimensions:
            bullets(model.missing_dimensions)
        else:
            st.caption("None identified.")
        if model.scope_coverage and model.scope_coverage.lower() != "exact":
            st.caption(
                f"Coverage is reported as **{model.scope_coverage}** — resolve the gaps above "
                "with the mission owner before fieldwork."
            )

    unmodelled_fields(model)

    # -- human-in-the-loop -------------------------------------------------
    draft = dict(run.payload)
    with st.expander("Review & adjust the perimeter", expanded=model.is_empty):
        st.caption(
            "This filter set is passed verbatim to every stage after it. Narrow it and those "
            "stages return less; widen it and they return more."
        )
        col_a, col_b = st.columns(2)
        with col_a:
            draft["primary_scope_driver"] = choice_editor(
                "Primary scope driver",
                model.primary_scope_driver,
                _DRIVERS,
                key=f"{run.key}_driver",
            )
        with col_b:
            draft["scope_coverage"] = choice_editor(
                "Scope coverage", model.scope_coverage, _COVERAGE, key=f"{run.key}_coverage"
            )

        draft["entity_filter"] = selection_editor(
            "Entity filter",
            model.entity_filter,
            metadata.entities,
            key=f"{run.key}_entities",
            help_text="Options come from the mission metadata you approved in stage 1.",
        )

        tab_risk, tab_activity, tab_other = st.tabs(
            ["Risk filter", "Activity filter", "Country & business line"]
        )
        with tab_risk:
            draft["risk_filter"] = selection_editor(
                "Risk families to focus on",
                model.risk_filter,
                metadata.risk_families,
                key=f"{run.key}_risks",
                help_text="Leave empty to keep every risk family in scope.",
            )
        with tab_activity:
            draft["activity_filter"] = list_editor(
                "Activities / processes", model.activity_filter, key=f"{run.key}_activities"
            )
        with tab_other:
            draft["country_filter"] = list_editor(
                "Countries", model.country_filter, key=f"{run.key}_countries"
            )
            draft["business_line_filter"] = selection_editor(
                "Business lines",
                model.business_line_filter,
                metadata.business_lines,
                key=f"{run.key}_bl",
            )

        draft["missing_dimensions"] = list_editor(
            "Missing dimensions",
            model.missing_dimensions,
            key=f"{run.key}_missing",
            help_text="Gaps the mission brief leaves open. Recorded in the briefing.",
        )
        draft["reasoning"] = list_editor(
            "Reasoning", model.reasoning, key=f"{run.key}_reasoning"
        )
        draft["brief_scope"] = text_editor(
            "Brief scope (as understood)", model.brief_scope, key=f"{run.key}_brief", height=80
        )
    return draft
