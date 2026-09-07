"""Stage 4 — methodology references."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ...models import Methodology
from ...state import MissionSession, StageRun
from ..common import bullets, empty_state, section, unmodelled_fields
from ..hitl import append_records_editor, list_editor


def render(session: MissionSession, run: StageRun) -> dict[str, Any]:
    model: Methodology = run.parsed()

    if not model.resolved_found:
        empty_state(
            model.message or "No registered methodology matched this mission",
            "There is no pre-registered methodological template for this exact scope. Fall back "
            "to the standard internal audit methodology — risk-based scoping, process "
            "walkthroughs, control testing, sampling, thematic review — and tailor it to the "
            "themes below. If you hold a local methodology note, add it here so it reaches "
            "the briefing.",
        )
    else:
        if model.message:
            st.success(model.message, icon="✅")
        section("Matched methodologies")
        for ref in model.references:
            header = " — ".join(p for p in (ref.ref_id, ref.title) if p) or "Reference"
            with st.container(border=True):
                st.markdown(f"**{header}**")
                meta = " · ".join(p for p in (ref.version, ref.scope_match) if p)
                if meta:
                    st.caption(meta)
                if ref.summary:
                    st.markdown(ref.summary)
                if ref.url:
                    st.markdown(f"[Open the methodology]({ref.url})")

    left, right = st.columns(2)
    with left:
        section("Implications")
        bullets(model.implications)
    with right:
        section("Approach to apply")
        bullets(model.recommended_approach)

    unmodelled_fields(model)

    # -- human-in-the-loop -------------------------------------------------
    draft = dict(run.payload)
    with st.expander("Review & adjust", expanded=not model.resolved_found):
        st.markdown("**Add a methodology the register does not hold**")
        added = append_records_editor(
            "Add methodology reference",
            key=f"{run.key}_refs",
            fields={
                "ref_id": "METH-…",
                "title": "Title of the note or programme",
                "url": "Intranet link (optional)",
            },
            help_text=(
                "The register is not exhaustive. Anything you add here is marked as analyst-"
                "sourced and carried into the briefing."
            ),
        )
        existing = [ref.model_dump(exclude_none=True) for ref in model.references]
        draft["references"] = [*existing, *added]
        if added:
            draft["found"] = True

        st.divider()
        draft["implications"] = list_editor(
            "Implications", model.implications, key=f"{run.key}_implications"
        )
        draft["recommended_approach"] = list_editor(
            "Approach to apply",
            model.recommended_approach,
            key=f"{run.key}_approach",
            help_text="The testing backbone the team will actually follow.",
        )
    return draft
