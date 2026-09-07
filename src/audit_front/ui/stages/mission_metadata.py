"""Stage 1 — mission metadata."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ...models import ActivityNode, MissionMetadata
from ...state import MissionSession, StageRun
from ..common import bullets, empty_state, field_row, section, tags, unmodelled_fields
from ..hitl import list_editor, text_editor


def _activity_markdown(nodes: list[ActivityNode], depth: int = 0) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        prefix = "  " * depth
        code = f"`{node.code}` " if node.code else ""
        lines.append(f"{prefix}- {code}{node.label or ''}".rstrip())
        if node.children:
            lines.extend(_activity_markdown(node.children, depth + 1))
    return lines


def render(session: MissionSession, run: StageRun) -> dict[str, Any]:
    model: MissionMetadata = run.parsed()

    field_row(
        [
            ("Mission ID", model.mission_id or session.mission_id),
            ("Countries", ", ".join(model.countries)),
            ("Audit cycle", model.audit_cycle),
            (
                "Main business line",
                f"`{model.main_business_line}`" if model.main_business_line else None,
            ),
            ("Entities in scope", len(model.entities) or None),
            ("Risk families", len(model.risk_families) or None),
        ]
    )

    if model.mission_name:
        st.markdown(f"##### {model.mission_name}")
    if model.brief_scope:
        st.markdown(f"> {model.brief_scope}")

    left, right = st.columns(2)
    with left:
        section("Entities in scope", help_text="The closed list this mission is defined against.")
        if model.entities:
            bullets(model.entities)
        else:
            empty_state(
                "No entities returned",
                "The mission has no entity list in the reference data. Check the scope stage "
                "carefully — without entities it will have to fall back to a broader axis.",
            )

        section("Business lines involved")
        tags(model.business_lines)

    with right:
        section("Key risk families (RiskL1)")
        bullets(model.risk_families)

    section(
        "Main activities / processes (ActivityThree)",
        help_text="The process tree the mission is mapped to.",
    )
    if model.activities:
        st.markdown("\n".join(_activity_markdown(model.activities)))
    else:
        st.caption("No activity mapping returned.")

    unmodelled_fields(model)

    # -- human-in-the-loop -------------------------------------------------
    draft = dict(run.payload)
    with st.expander("Review & adjust metadata", expanded=False):
        st.caption(
            "Reference data goes stale between cycles. Corrections you make here define the "
            "options offered to the scope stage."
        )
        draft["brief_scope"] = text_editor(
            "Brief scope", model.brief_scope, key=f"{run.key}_brief", height=90
        )
        col_left, col_right = st.columns(2)
        with col_left:
            draft["entities"] = list_editor(
                "Entities in scope", model.entities, key=f"{run.key}_entities"
            )
            draft["countries"] = list_editor(
                "Countries", model.countries, key=f"{run.key}_countries"
            )
        with col_right:
            draft["risk_families"] = list_editor(
                "Key risk families", model.risk_families, key=f"{run.key}_risks"
            )
            draft["business_lines"] = list_editor(
                "Business lines", model.business_lines, key=f"{run.key}_bl"
            )
    return draft
