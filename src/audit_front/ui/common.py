"""Shared rendering helpers and the app's CSS.

Everything visual that more than one stage needs lives here, so the six stage
modules stay about *their* content rather than about layout.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

import streamlit as st

from ..state import StageRun, StageStatus

CSS = """
<style>
  /* Tighten Streamlit's default vertical rhythm — this is a dense, working tool. */
  .block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1180px; }
  section[data-testid="stSidebar"] { width: 340px !important; }

  .af-chip {
    display: inline-flex; align-items: center; gap: .4em;
    padding: .18em .7em; border-radius: 999px;
    font-size: .78rem; font-weight: 600; line-height: 1.5;
    border: 1px solid currentColor;
  }
  .af-chip-dot { font-size: .9em; }

  .af-hero {
    border: 1px solid rgba(0,0,0,.09); border-left: 4px solid #E60028;
    border-radius: 8px; padding: 1rem 1.25rem; background: #FBFBFC; margin-bottom: 1.1rem;
  }
  .af-hero h2 { margin: 0 0 .25rem 0; font-size: 1.35rem; line-height: 1.3; }
  .af-hero .af-sub { color: #5F6368; font-size: .88rem; }

  .af-purpose {
    color: #3C4043; font-size: .92rem; line-height: 1.55;
    border-left: 3px solid #DADCE0; padding: .1rem 0 .1rem .9rem; margin: .2rem 0 1rem 0;
  }

  .af-hitl {
    background: #FFF8E9; border: 1px solid #F2D9A6; border-radius: 8px;
    padding: .8rem 1rem; font-size: .89rem; line-height: 1.55; margin-bottom: 1rem;
  }
  .af-hitl strong { color: #8A5A00; }

  .af-empty {
    border: 1px dashed #C8CBD0; border-radius: 8px; background: #FAFAFB;
    padding: 1.1rem 1.25rem; margin: .4rem 0 1rem 0;
  }
  .af-empty .af-empty-title { font-weight: 600; margin-bottom: .3rem; }
  .af-empty .af-empty-body { color: #5F6368; font-size: .9rem; line-height: 1.6; }

  .af-tag {
    display: inline-block; padding: .12em .55em; margin: 0 .3em .35em 0;
    border-radius: 5px; background: #EEF0F3; border: 1px solid #DFE2E7;
    font-size: .8rem; font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
  }

  .af-meta { color: #70757A; font-size: .8rem; }

  /* Sidebar stepper buttons: left-align the label so the status icon lines up. */
  section[data-testid="stSidebar"] .stButton button {
    text-align: left; justify-content: flex-start;
  }

  .af-diff-added { color: #1E8E3E; }
  .af-diff-removed { color: #D93025; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def rerun() -> None:
    """`st.rerun` with a fallback for older Streamlit builds."""
    fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if fn is not None:
        fn()


def toast(message: str, icon: str | None = None) -> None:
    fn = getattr(st, "toast", None)
    if fn is not None:
        fn(message, icon=icon)


# ---------------------------------------------------------------------------
# Chips, headers, empty states
# ---------------------------------------------------------------------------


def status_chip(status: StageStatus, *, stale: bool = False, edited: bool = False) -> str:
    """Inline HTML chip describing a stage's state."""
    if stale:
        return (
            '<span class="af-chip" style="color:#B06000;background:#FFF4E5;">'
            '<span class="af-chip-dot">◆</span>Stale — upstream changed</span>'
        )
    label = status.label + (" · edited" if edited and status is not StageStatus.PENDING else "")
    return (
        f'<span class="af-chip" style="color:{status.color};background:{status.color}14;">'
        f'<span class="af-chip-dot">{status.icon}</span>{escape(label)}</span>'
    )


def hero(title: str, subtitle: str = "", chips_html: str = "") -> None:
    st.markdown(
        f'<div class="af-hero"><h2>{escape(title)}</h2>'
        + (f'<div class="af-sub">{escape(subtitle)}</div>' if subtitle else "")
        + (f'<div style="margin-top:.55rem;">{chips_html}</div>' if chips_html else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def purpose(text: str) -> None:
    st.markdown(f'<div class="af-purpose">{escape(text)}</div>', unsafe_allow_html=True)


def hitl_note(text: str) -> None:
    st.markdown(
        f'<div class="af-hitl"><strong>What to check here — </strong>{escape(text)}</div>',
        unsafe_allow_html=True,
    )


def empty_state(title: str, body: str) -> None:
    """A deliberate 'nothing here, and here is what that means' block.

    Three of the six stages routinely return nothing. Rendering that as a
    blank area would read as a broken page; it is actually a result.
    """
    st.markdown(
        f'<div class="af-empty"><div class="af-empty-title">{escape(title)}</div>'
        f'<div class="af-empty-body">{escape(body)}</div></div>',
        unsafe_allow_html=True,
    )


def tags(items: list[str]) -> None:
    if not items:
        st.caption("—")
        return
    html = "".join(f'<span class="af-tag">{escape(str(item))}</span>' for item in items)
    st.markdown(html, unsafe_allow_html=True)


def bullets(items: list[str], *, empty: str = "—") -> None:
    if not items:
        st.caption(empty)
        return
    st.markdown("\n".join(f"- {item}" for item in items))


def field_row(pairs: list[tuple[str, Any]]) -> None:
    """Label/value pairs laid out in equal columns, skipping empty values."""
    present = [(label, value) for label, value in pairs if value not in (None, "", [], {})]
    if not present:
        return
    for chunk_start in range(0, len(present), 3):
        chunk = present[chunk_start : chunk_start + 3]
        for column, (label, value) in zip(st.columns(len(chunk)), chunk, strict=False):
            with column:
                st.caption(label)
                st.markdown(f"**{value}**")


def section(title: str, *, help_text: str | None = None) -> None:
    st.markdown(f"##### {title}")
    if help_text:
        st.caption(help_text)


def meta_line(run: StageRun) -> None:
    """Timing / provenance strip under a stage header."""
    parts: list[str] = []
    if run.run_count:
        parts.append(f"run #{run.run_count}")
    if run.duration_s is not None:
        parts.append(f"{run.duration_s:.1f}s")
    if run.finished_at:
        parts.append(run.finished_at.strftime("%Y-%m-%d %H:%M UTC"))
    if run.trace_id:
        parts.append(f"trace `{run.trace_id}`")
    if parts:
        st.markdown(f'<div class="af-meta">{" · ".join(parts)}</div>', unsafe_allow_html=True)


def warnings_block(run: StageRun) -> None:
    for warning in run.warnings:
        st.warning(warning, icon="⚠️")


def raw_payload(run: StageRun) -> None:
    """Always-available escape hatch: the exact JSON behind the rendering."""
    with st.expander("Raw payload", expanded=False):
        if run.edited:
            left, right = st.columns(2)
            with left:
                st.caption("Agent output")
                st.json(run.ai_payload or {}, expanded=False)
            with right:
                st.caption("Analyst version (used downstream)")
                st.json(run.analyst_payload or {}, expanded=False)
        else:
            st.json(run.payload, expanded=False)
        st.download_button(
            "Download this stage as JSON",
            data=json.dumps(run.payload, indent=2, ensure_ascii=False),
            file_name=f"{run.key}.json",
            mime="application/json",
            key=f"dl_raw_{run.key}",
        )


def unmodelled_fields(model: Any) -> None:
    """Surface backend fields this front-end does not know about.

    Keeps the UI honest when the backend contract moves ahead of it, instead
    of silently dropping data the analyst may need.
    """
    extras = model.extras() if hasattr(model, "extras") else {}
    if not extras:
        return
    with st.expander(f"Additional backend fields ({len(extras)})", expanded=False):
        st.caption(
            "Returned by the backend but not modelled by this front-end. "
            "Worth adding to the UI if they matter."
        )
        st.json(extras, expanded=True)
