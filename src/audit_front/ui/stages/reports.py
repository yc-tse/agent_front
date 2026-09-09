"""Stage 5 — historical 3LOD reports.

The list matters less than the positions in it. A mission that contradicts a
position IGAD took eighteen months ago needs to know at scoping, not at the
clearance meeting — so IGAD positions get their own section rather than being
buried in per-report detail.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ...models import HistoricalReports
from ...state import MissionSession, StageRun
from ..common import bullets, empty_state, section, unmodelled_fields
from ..hitl import append_records_editor, list_editor, record_table_editor

_COLUMNS = {
    "report_id": "Ref",
    "title": "Title",
    "line_of_defence": "Line",
    "issuer": "Issuer",
    "entity": "Entity",
    "published_date": "Published",
    "rating": "Rating",
    "scope_match": "Relevance",
    "source": "Source",
}

# Ratings that mean the position is adverse and still standing.
_ADVERSE = {"unsatisfactory", "needs improvement", "inadequate", "poor"}


def _frame(model: HistoricalReports) -> pd.DataFrame:
    rows = [
        {label: getattr(report, field, None) for field, label in _COLUMNS.items()}
        for report in model.reports
    ]
    return pd.DataFrame(rows, columns=list(_COLUMNS.values()))


def _adverse(model: HistoricalReports) -> list[Any]:
    return [r for r in model.reports if (r.rating or "").strip().lower() in _ADVERSE]


def render(session: MissionSession, run: StageRun) -> dict[str, Any]:
    model: HistoricalReports = run.parsed()

    if not model.resolved_found:
        empty_state(
            model.message or "No prior 3LOD report found on this perimeter",
            "Nothing on record from the first, second or third line for these entities. That "
            "makes the mission a first look rather than a re-examination — but the search keys "
            "on this perimeter, so a report on a sister entity, a 2LOD review filed locally or "
            "a regulator letter will not appear. Add anything you hold below.",
        )
    else:
        adverse = _adverse(model)
        metrics = st.columns(4)
        metrics[0].metric("Reports found", len(model.reports))
        metrics[1].metric("From 3LOD", len(model.third_line_reports))
        metrics[2].metric("Adverse ratings", len(adverse))
        metrics[3].metric("Lines covered", len(model.lines_covered) or "—")

        if adverse:
            names = ", ".join(r.report_id or r.title or "report" for r in adverse)
            st.warning(
                f"Adverse rating(s) on record for this perimeter: {names}. Establish whether "
                "the position has since been lifted before restating or contradicting it.",
                icon="⚠️",
            )
        if model.message:
            st.caption(model.message)

        section(
            "Reports on the perimeter",
            help_text="First, second and third line, plus external where relevant.",
        )
        st.dataframe(_frame(model), width="stretch", hide_index=True)

        with st.expander("Report detail and key messages", expanded=False):
            for report in model.reports:
                header = " — ".join(p for p in (report.report_id, report.title) if p)
                st.markdown(f"**{header or 'Report'}**")
                st.caption(
                    " · ".join(
                        p
                        for p in (
                            report.line_of_defence,
                            report.issuer,
                            report.entity,
                            report.published_date,
                            f"period {report.period_covered}" if report.period_covered else None,
                            f"rating: {report.rating}" if report.rating else None,
                        )
                        if p
                    )
                )
                if report.key_messages:
                    bullets(report.key_messages)
                if report.igad_position:
                    st.markdown(f"> **IGAD position** — {report.igad_position}")
                if report.url:
                    st.markdown(f"[Open the report]({report.url})")
                st.divider()

    positions = model.resolved_positions()
    section(
        "IGAD positions",
        help_text="What internal audit has already said about this perimeter, and where.",
    )
    bullets(
        positions,
        empty="No IGAD position on record — this mission establishes the first one.",
    )

    left, right = st.columns(2)
    with left:
        section("Key messages across the reports")
        bullets(model.key_messages)
    with right:
        section("Implications")
        bullets(model.implications)

    unmodelled_fields(model)

    # -- human-in-the-loop -------------------------------------------------
    draft = dict(run.payload)
    with st.expander("Review & adjust", expanded=not model.resolved_found):
        kept: list[dict[str, Any]] = []
        if model.reports:
            st.markdown("**Reports to carry into the briefing**")
            kept = record_table_editor(
                "Reports",
                [report.model_dump(exclude_none=True) for report in model.reports],
                key=f"{run.key}_reports",
                columns=_COLUMNS,
                help_text=(
                    "Untick a report whose position does not actually bear on this mission — "
                    "superseded, out of scope, or about a different process. Both versions "
                    "stay in the export."
                ),
            )
            st.divider()

        st.markdown("**Add a report the search did not find**")
        added = append_records_editor(
            "Add report",
            key=f"{run.key}_add",
            fields={
                "report_id": "IGAD-…",
                "title": "Report title",
                "line_of_defence": "1LOD / 2LOD / 3LOD / External",
                "issuer": "IGAD, Compliance, regulator…",
                "entity": "Entity concerned",
                "published_date": "YYYY-MM-DD",
                "rating": "Opinion or rating",
                "igad_position": "The position taken, if any",
            },
            help_text=(
                "Reports on sister entities, locally filed 2LOD reviews and regulator "
                "correspondence rarely surface in the search but are read as precedent."
            ),
        )
        draft["reports"] = [*kept, *added]
        if added:
            draft["found"] = True

        st.divider()
        draft["igad_positions"] = list_editor(
            "IGAD positions",
            positions,
            key=f"{run.key}_positions",
            help_text=(
                "State each position as the mission will have to live with it. This is what "
                "the briefing carries forward."
            ),
        )
        col_a, col_b = st.columns(2)
        with col_a:
            draft["key_messages"] = list_editor(
                "Key messages", model.key_messages, key=f"{run.key}_messages"
            )
        with col_b:
            draft["implications"] = list_editor(
                "Implications", model.implications, key=f"{run.key}_implications"
            )
    return draft
