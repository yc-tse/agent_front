"""Stage 3 — operational risk events in scope."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ...models import RiskEvents
from ...state import MissionSession, StageRun
from ..common import bullets, empty_state, section, unmodelled_fields
from ..hitl import list_editor, record_table_editor

_COLUMNS = {
    "event_id": "Ref",
    "event_date": "Date",
    "entity": "Entity",
    "risk_category": "Risk category",
    "gross_amount": "Gross",
    "net_amount": "Net",
    "status": "Status",
}


def _events_frame(model: RiskEvents) -> pd.DataFrame:
    rows = [
        {label: getattr(event, field, None) for field, label in _COLUMNS.items()}
        for event in model.events
    ]
    return pd.DataFrame(rows, columns=list(_COLUMNS.values()))


def render(session: MissionSession, run: StageRun) -> dict[str, Any]:
    model: RiskEvents = run.parsed()
    count = model.resolved_count

    if count == 0:
        empty_state(
            "No operational loss events surfaced for this perimeter",
            "This is a result, not a gap in the tool. It means no structured loss data was "
            "retrieved for the entities you approved — it does not prove that no incidents "
            "occurred. Plan to lean on qualitative sources during fieldwork: risk maps, RCSA, "
            "incident logs, complaints, HR cases and compliance alerts.",
        )
    else:
        open_events = [e for e in model.events if (e.status or "").lower() == "open"]
        metrics = st.columns(4)
        metrics[0].metric("Events in scope", count)
        metrics[1].metric(
            "Gross loss",
            f"{model.total_amount:,.0f} {model.currency or ''}".strip()
            if model.total_amount is not None
            else "—",
        )
        metrics[2].metric("Still open", len(open_events))
        metrics[3].metric("Period", model.period or "—")

        section("Loss events")
        frame = _events_frame(model)
        st.dataframe(
            frame,
            width="stretch",
            hide_index=True,
            column_config={
                "Gross": st.column_config.NumberColumn(format="%.0f"),
                "Net": st.column_config.NumberColumn(format="%.0f"),
            },
        )
        with st.expander("Event descriptions", expanded=False):
            for event in model.events:
                header = " — ".join(p for p in (event.event_id, event.title) if p)
                st.markdown(f"**{header or 'Event'}**")
                st.caption(
                    " · ".join(
                        p
                        for p in (
                            event.entity,
                            event.event_date,
                            event.risk_category,
                            event.status,
                        )
                        if p
                    )
                )
                if event.description:
                    st.markdown(event.description)
                st.divider()

    section("Interpretation for the mission")
    bullets(
        model.interpretation,
        empty="The agent returned no interpretation — add yours below before approving.",
    )

    unmodelled_fields(model)

    # -- human-in-the-loop -------------------------------------------------
    draft = dict(run.payload)
    with st.expander("Review & adjust", expanded=count == 0):
        if model.events:
            st.markdown("**Events to keep in the perimeter**")
            kept = record_table_editor(
                "Events",
                [event.model_dump(exclude_none=True) for event in model.events],
                key=f"{run.key}_events",
                columns=_COLUMNS,
                help_text=(
                    "Uncheck an event you judge out of scope. Excluded events do not reach the "
                    "briefing, and the exclusion is recorded."
                ),
            )
            draft["events"] = kept
            draft["total_count"] = len(kept)
            draft["total_amount"] = sum(float(e.get("gross_amount") or 0) for e in kept) or None
            st.divider()

        draft["interpretation"] = list_editor(
            "Interpretation for the mission",
            model.interpretation,
            key=f"{run.key}_interpretation",
            help_text="What these events (or their absence) mean for how you plan fieldwork.",
        )
        draft["period"] = st.text_input(
            "Period covered",
            value=model.period or "",
            key=f"hitl_{run.key}_period",
            placeholder="e.g. 2023-01-01 to 2026-08-31",
        ).strip()
    return draft
