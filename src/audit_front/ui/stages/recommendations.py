"""Stage 5 — historical recommendations."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ...models import HistoricalRecommendations
from ...state import MissionSession, StageRun
from ..common import bullets, empty_state, section, unmodelled_fields
from ..hitl import append_records_editor, list_editor, record_table_editor

_COLUMNS = {
    "rec_id": "Ref",
    "title": "Title",
    "entity": "Entity",
    "risk_family": "Risk family",
    "criticality": "Criticality",
    "status": "Status",
    "due_date": "Due",
    "source": "Source",
}


def _frame(model: HistoricalRecommendations) -> pd.DataFrame:
    rows = [
        {label: getattr(rec, field, None) for field, label in _COLUMNS.items()}
        for rec in model.recommendations
    ]
    return pd.DataFrame(rows, columns=list(_COLUMNS.values()))


def render(session: MissionSession, run: StageRun) -> dict[str, Any]:
    model: HistoricalRecommendations = run.parsed()

    if not model.resolved_found:
        empty_state(
            model.message or "No previous recommendation on this perimeter",
            "The mission is not constrained by a backlog for this exact combined scope — treat "
            "it as a baseline review. The search keys on this mission ID, so recommendations "
            "raised by narrower prior missions (an AML-only or HR-only review of the same "
            "entities) will not appear. Check locally and add anything you find.",
        )
    else:
        open_items = model.open_items
        high = [r for r in open_items if (r.criticality or "").lower() in {"high", "critical"}]
        metrics = st.columns(3)
        metrics[0].metric("Recommendations found", len(model.recommendations))
        metrics[1].metric("Still open", len(open_items))
        metrics[2].metric("Open & high/critical", len(high))
        if high:
            st.warning(
                "Open high-criticality recommendations touch this perimeter — verify their "
                "remediation status before scoping new testing.",
                icon="⚠️",
            )
        if model.message:
            st.caption(model.message)

        section("Recommendations on the perimeter")
        st.dataframe(_frame(model), width="stretch", hide_index=True)
        with st.expander("Recommendation details", expanded=False):
            for rec in model.recommendations:
                header = " — ".join(p for p in (rec.rec_id, rec.title) if p)
                st.markdown(f"**{header or 'Recommendation'}**")
                st.caption(
                    " · ".join(
                        p
                        for p in (
                            rec.mission_ref,
                            rec.entity,
                            rec.criticality,
                            rec.status,
                            f"due {rec.due_date}" if rec.due_date else None,
                        )
                        if p
                    )
                )
                if rec.description:
                    st.markdown(rec.description)
                st.divider()

    section("Implications")
    bullets(model.implications)

    unmodelled_fields(model)

    # -- human-in-the-loop -------------------------------------------------
    draft = dict(run.payload)
    with st.expander("Review & adjust", expanded=not model.resolved_found):
        kept: list[dict[str, Any]] = []
        if model.recommendations:
            st.markdown("**Recommendations to carry into the briefing**")
            kept = record_table_editor(
                "Recommendations",
                [rec.model_dump(exclude_none=True) for rec in model.recommendations],
                key=f"{run.key}_recs",
                columns=_COLUMNS,
                help_text="Uncheck anything that does not actually bear on this mission.",
            )
            st.divider()

        st.markdown("**Add a recommendation the search did not find**")
        added = append_records_editor(
            "Add recommendation",
            key=f"{run.key}_add",
            fields={
                "rec_id": "REC-…",
                "title": "What was recommended",
                "mission_ref": "Originating mission",
                "entity": "Entity concerned",
                "status": "Open / Closed",
                "criticality": "High / Medium / Low",
            },
            help_text=(
                "Recommendations from narrower prior missions on the same entities belong here."
            ),
        )
        draft["recommendations"] = [*kept, *added]
        if added:
            draft["found"] = True

        st.divider()
        draft["implications"] = list_editor(
            "Implications", model.implications, key=f"{run.key}_implications"
        )
    return draft
