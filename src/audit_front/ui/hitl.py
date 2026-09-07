"""Human-in-the-loop controls: the editors and the review action bar.

The design rule throughout: **the analyst's version is what flows downstream.**
Editing is not annotation. When a scope filter is narrowed here, the next
stage is called with the narrowed filter, and the export says the human
changed it.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ..diffing import change_summary, has_changes
from ..pipeline import StageSpec, next_stage
from ..runner import run_stage
from ..state import MissionSession, StageRun
from .common import rerun, toast
from .session import set_active_stage

# ---------------------------------------------------------------------------
# Field editors
# ---------------------------------------------------------------------------


def list_editor(
    label: str,
    items: list[str],
    *,
    key: str,
    help_text: str | None = None,
    height: int | None = None,
    placeholder: str = "One item per line",
) -> list[str]:
    """Edit a list of strings as one-per-line text.

    A text area beats a row of widgets here: analysts paste these lists in
    from other tools, and reordering by editing text is faster than dragging.
    """
    default = "\n".join(items)
    rows = max(3, min(14, len(items) + 2))
    raw = st.text_area(
        label,
        value=default,
        key=f"hitl_{key}",
        help=help_text,
        height=height or rows * 26,
        placeholder=placeholder,
    )
    return [line.strip() for line in raw.splitlines() if line.strip()]


def text_editor(
    label: str, value: str | None, *, key: str, height: int = 110, help_text: str | None = None
) -> str:
    return st.text_area(
        label, value=value or "", key=f"hitl_{key}", height=height, help=help_text
    ).strip()


def line_editor(label: str, value: str | None, *, key: str, help_text: str | None = None) -> str:
    return st.text_input(label, value=value or "", key=f"hitl_{key}", help=help_text).strip()


def choice_editor(
    label: str, value: str | None, options: list[str], *, key: str, help_text: str | None = None
) -> str:
    """Select from known values while still allowing a backend value we don't know."""
    choices = list(dict.fromkeys([*options, value] if value else options))
    choices = [c for c in choices if c]
    index = choices.index(value) if value in choices else 0
    if not choices:
        return line_editor(label, value, key=key, help_text=help_text)
    return st.selectbox(label, choices, index=index, key=f"hitl_{key}", help=help_text)


def selection_editor(
    label: str,
    selected: list[str],
    options: list[str],
    *,
    key: str,
    help_text: str | None = None,
) -> list[str]:
    """Multiselect over known options, with a free-text escape for the rest.

    Reference data is never complete — an analyst who knows an eighth entity
    belongs in scope must be able to add it without leaving the app.
    """
    all_options = list(dict.fromkeys([*options, *selected]))
    chosen = st.multiselect(
        label,
        all_options,
        default=[s for s in selected if s in all_options],
        key=f"hitl_{key}",
        help=help_text,
    )
    extra = st.text_input(
        "Add values not in the reference list",
        key=f"hitl_{key}_extra",
        placeholder="Comma-separated; added to the selection above",
        label_visibility="collapsed",
    )
    manual = [part.strip() for part in extra.split(",") if part.strip()]
    return list(dict.fromkeys([*chosen, *manual]))


def record_table_editor(
    label: str,
    records: list[dict[str, Any]],
    *,
    key: str,
    columns: dict[str, str],
    help_text: str | None = None,
) -> list[dict[str, Any]]:
    """Include/exclude records with a checkbox each, keeping the excluded visible.

    Exclusion is a judgement the analyst must be able to justify later, so the
    UI keeps every dropped row on screen rather than deleting it silently.
    """
    if not records:
        st.caption("Nothing to review here.")
        return []
    if help_text:
        st.caption(help_text)

    kept: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        identifier = str(record.get("event_id") or record.get("rec_id") or index)
        summary = " · ".join(
            str(record.get(field, "")) for field in columns if record.get(field)
        )
        include = st.checkbox(
            summary or f"Record {index + 1}",
            value=True,
            key=f"hitl_{key}_keep_{identifier}",
        )
        if include:
            kept.append(record)
    dropped = len(records) - len(kept)
    if dropped:
        st.warning(
            f"{dropped} record(s) excluded from the perimeter. "
            "Record why in the review note — the export keeps both versions.",
            icon="✂️",
        )
    return kept


def append_records_editor(
    label: str,
    *,
    key: str,
    fields: dict[str, str],
    help_text: str | None = None,
) -> list[dict[str, Any]]:
    """A small form for records the backend did not find but the analyst holds.

    Stage 4 and stage 5 both return "nothing found" far more often than they
    return data, and the sample output itself says to check locally. Without
    this, that instruction has nowhere to land.
    """
    with st.form(f"hitl_{key}_form", clear_on_submit=True):
        if help_text:
            st.caption(help_text)
        values: dict[str, Any] = {}
        columns = st.columns(min(3, len(fields)))
        for index, (field, placeholder) in enumerate(fields.items()):
            with columns[index % len(columns)]:
                values[field] = st.text_input(
                    field.replace("_", " ").title(),
                    key=f"hitl_{key}_{field}",
                    placeholder=placeholder,
                ).strip()
        submitted = st.form_submit_button(label, width="content")

    store_key = f"hitl_{key}_added"
    added: list[dict[str, Any]] = st.session_state.setdefault(store_key, [])
    if submitted and any(values.values()):
        added.append({**{k: v for k, v in values.items() if v}, "source": "analyst"})
        toast("Added to this stage", icon="➕")
        rerun()
    if added:
        noun = "entry" if len(added) == 1 else "entries"
        st.caption(f"{len(added)} {noun} added by you:")
        for index, record in enumerate(added):
            row, remove = st.columns([0.92, 0.08])
            with row:
                st.markdown(
                    "· " + " — ".join(str(v) for k, v in record.items() if k != "source" and v)
                )
            with remove:
                if st.button("✕", key=f"hitl_{key}_rm_{index}", help="Remove"):
                    added.pop(index)
                    rerun()
    return added


# ---------------------------------------------------------------------------
# Review action bar
# ---------------------------------------------------------------------------


def review_bar(
    session: MissionSession,
    spec: StageSpec,
    client: Any,
    *,
    draft: dict[str, Any] | None,
) -> None:
    """Approve / save / revert / re-run — the checkpoint itself."""
    run: StageRun = session.stage(spec.key)
    changed = draft is not None and has_changes(spec, run.payload, draft)
    following = next_stage(spec.key)

    st.divider()

    if changed:
        st.info(
            "You have unsaved changes. Approving saves them; they become the input "
            "for the stages that follow.",
            icon="✏️",
        )

    note_col, approve_col = st.columns([0.62, 0.38])
    with note_col:
        note = st.text_input(
            "Review note (optional)",
            key=f"hitl_note_{spec.key}",
            value=run.review_note or "",
            placeholder="Why you accepted, changed, or narrowed this — kept in the audit trail",
        )
    with approve_col:
        st.write("")  # baseline alignment with the text input
        approve_label = (
            f"Approve & continue to {following.short_label}"
            if following
            else "Approve — pipeline complete"
        )
        if st.button(
            approve_label,
            type="primary",
            width="stretch",
            key=f"approve_{spec.key}",
        ):
            if changed and draft is not None:
                session.apply_edit(spec.key, draft, detail=change_summary(spec, run.payload, draft))
            session.approve(spec.key, note.strip() or None)
            toast(f"{spec.short_label} approved", icon="✅")
            if following:
                set_active_stage(following.key)
            rerun()

    save_col, revert_col, rerun_col = st.columns(3)
    with save_col:
        if st.button(
            "Save changes",
            disabled=not changed,
            width="stretch",
            key=f"save_{spec.key}",
            help="Keep your edits without approving the stage yet",
        ):
            if draft is not None:
                session.apply_edit(spec.key, draft, detail=change_summary(spec, run.payload, draft))
                toast("Changes saved", icon="💾")
                rerun()
    with revert_col:
        if st.button(
            "Revert to agent output",
            disabled=not run.edited,
            width="stretch",
            key=f"revert_{spec.key}",
            help="Discard your edits and go back to what the agent produced",
        ):
            session.revert_edit(spec.key)
            _clear_stage_widgets(spec.key)
            toast("Reverted to the agent's output", icon="↩️")
            rerun()
    with rerun_col:
        rerun_open = st.toggle(
            "Ask the agent again",
            key=f"rerun_toggle_{spec.key}",
            help="Send the stage back with an instruction instead of editing by hand",
        )

    if rerun_open:
        instruction = st.text_area(
            "What should the agent do differently?",
            key=f"hitl_feedback_{spec.key}",
            value=run.feedback or "",
            height=90,
            placeholder=(
                "e.g. Treat this as process-driven rather than entity-driven, and keep only "
                "the entities that actually operate leasing contracts."
            ),
        )
        confirm, warn = st.columns([0.34, 0.66])
        with confirm:
            if st.button(
                "Re-run this stage",
                width="stretch",
                key=f"do_rerun_{spec.key}",
                disabled=not instruction.strip(),
            ):
                with st.spinner(f"Re-running {spec.label.lower()}…"):
                    run_stage(session, client, spec, feedback=instruction.strip())
                _clear_stage_widgets(spec.key)
                rerun()
        with warn:
            st.caption(
                "A re-run replaces the agent output and discards your manual edits "
                "to this stage."
            )


def _clear_stage_widgets(stage_key: str) -> None:
    """Drop cached widget values so the editors reload from the new payload."""
    prefixes = (f"hitl_{stage_key}", f"hitl_note_{stage_key}")
    for key in [k for k in st.session_state if isinstance(k, str) and k.startswith(prefixes)]:
        del st.session_state[key]
