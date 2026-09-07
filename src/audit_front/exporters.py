"""Turn a session into something the analyst can take away.

Two formats, two purposes:

* **Markdown** — the readable deliverable, laid out in the same six sections
  as the agent's own output so it is recognisable to anyone who has seen the
  raw run, plus a provenance appendix.
* **JSON** — the complete record: every AI payload, every analyst override,
  and the full audit trail. This is what makes an AI-assisted deliverable
  defensible after the fact.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .models import (
    Briefing,
    HistoricalRecommendations,
    Methodology,
    MissionMetadata,
    RiskEvents,
    ScopeUnderstanding,
)
from .pipeline import STAGES, get_stage
from .state import MissionSession, StageRun, StageStatus

_NOT_RUN = "_Stage not run._"


# ---------------------------------------------------------------------------
# Small markdown helpers
# ---------------------------------------------------------------------------


def _bullets(items: list[str], indent: int = 0) -> list[str]:
    pad = "  " * indent
    return [f"{pad}- {item}" for item in items if str(item).strip()]


def _field(label: str, value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return f"- **{label}:** {value}"


def _amount(value: float | None, currency: str | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f} {currency or ''}".strip()


def _activity_lines(nodes: list[Any], depth: int = 0) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines.append(f"{'  ' * depth}- {node.display}")
        if node.children:
            lines.extend(_activity_lines(node.children, depth + 1))
    return lines


# ---------------------------------------------------------------------------
# Per-stage sections
# ---------------------------------------------------------------------------


def _metadata_md(model: MissionMetadata) -> list[str]:
    lines = [
        line
        for line in (
            _field("Mission ID", model.mission_id),
            _field("Mission name", model.mission_name),
            _field("Brief scope", model.brief_scope),
            _field("Main business line", model.main_business_line),
            _field("Audit cycle", model.audit_cycle),
            _field("Countries", ", ".join(model.countries)),
        )
        if line
    ]
    if model.entities:
        lines += ["", "**Entities in scope:**", *_bullets(model.entities)]
    if model.risk_families:
        lines += ["", "**Key risk families (RiskL1):**", *_bullets(model.risk_families)]
    if model.activities:
        lines += ["", "**Main activities / processes (ActivityThree):**"]
        lines += _activity_lines(model.activities)
    if model.business_lines:
        lines += ["", "**Business lines involved:**", *_bullets(model.business_lines)]
    return lines


def _scope_md(model: ScopeUnderstanding) -> list[str]:
    lines = [
        line
        for line in (
            _field("Primary scope driver", model.primary_scope_driver),
            _field("Scope coverage", model.scope_coverage),
        )
        if line
    ]
    lines.append(
        "- **Missing dimensions:** "
        + ("None identified." if not model.missing_dimensions else "")
    )
    if model.missing_dimensions:
        lines += _bullets(model.missing_dimensions, indent=1)

    filters = [
        ("Entity filter", model.entity_filter),
        ("Country filter", model.country_filter),
        ("Risk filter", model.risk_filter),
        ("Activity filter", model.activity_filter),
        ("Business line filter", model.business_line_filter),
    ]
    active = [(label, values) for label, values in filters if values]
    if active:
        lines += ["", "**Scope definition used for filtering:**"]
        for label, values in active:
            lines += [f"- {label}:", *_bullets(values, indent=1)]
    if model.reasoning:
        lines += ["", "**Reasoning:**", *_bullets(model.reasoning)]
    return lines


def _risk_events_md(model: RiskEvents) -> list[str]:
    lines: list[str] = []
    if model.resolved_count == 0:
        lines.append("- **Operational losses identified:** none surfaced for this perimeter.")
    else:
        lines.append(f"- **Operational losses identified:** {model.resolved_count}")
        if model.total_amount is not None:
            lines.append(f"- **Total gross amount:** {_amount(model.total_amount, model.currency)}")
    if model.period:
        lines.append(f"- **Period covered:** {model.period}")

    if model.events:
        lines += [
            "",
            "| Ref | Date | Entity | Risk category | Gross | Status |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for event in model.events:
            lines.append(
                "| {ref} | {date} | {entity} | {cat} | {amount} | {status} |".format(
                    ref=event.event_id or "—",
                    date=event.event_date or "—",
                    entity=event.entity or "—",
                    cat=event.risk_category or "—",
                    amount=_amount(event.gross_amount, event.currency or model.currency),
                    status=event.status or "—",
                )
            )
    if model.interpretation:
        lines += ["", "**Interpretation for the mission:**", *_bullets(model.interpretation)]
    return lines


def _methodology_md(model: Methodology) -> list[str]:
    lines: list[str] = []
    if model.message:
        lines.append(f"- **Result:** {model.message}")
    elif not model.resolved_found:
        lines.append("- **Result:** no registered methodology matched this mission.")
    for ref in model.references:
        header = " — ".join(p for p in (ref.ref_id, ref.title) if p) or "Reference"
        lines += ["", f"**{header}**"]
        lines += [
            line
            for line in (
                _field("Version", ref.version),
                _field("Scope match", ref.scope_match),
                _field("Link", ref.url),
            )
            if line
        ]
        if ref.summary:
            lines.append(f"- {ref.summary}")
    if model.implications:
        lines += ["", "**Implications:**", *_bullets(model.implications)]
    if model.recommended_approach:
        lines += ["", "**Approach to apply:**", *_bullets(model.recommended_approach)]
    return lines


def _recommendations_md(model: HistoricalRecommendations) -> list[str]:
    lines: list[str] = []
    if model.message:
        lines.append(f"- **Result:** {model.message}")
    elif not model.resolved_found:
        lines.append("- **Result:** no previous recommendation on this perimeter.")
    if model.recommendations:
        lines += [
            "",
            "| Ref | Title | Entity | Criticality | Status | Due | Source |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for rec in model.recommendations:
            lines.append(
                "| {ref} | {title} | {entity} | {crit} | {status} | {due} | {source} |".format(
                    ref=rec.rec_id or "—",
                    title=rec.title or "—",
                    entity=rec.entity or "—",
                    crit=rec.criticality or "—",
                    status=rec.status or "—",
                    due=rec.due_date or "—",
                    source=rec.source or "backend",
                )
            )
    if model.implications:
        lines += ["", "**Implications:**", *_bullets(model.implications)]
    return lines


def _briefing_md(model: Briefing) -> list[str]:
    if model.markdown and not any(
        [model.objective, model.thematic_axes, model.perimeter, model.risk_landscape]
    ):
        return [model.markdown]

    lines: list[str] = []
    if model.objective:
        lines += ["**Mission objective (operational view)**", "", model.objective]
    if model.perimeter:
        lines += [
            "",
            "**Perimeter to use for all pre-mission work**",
            "",
            *_bullets(model.perimeter),
        ]
    if model.thematic_axes:
        lines += ["", "**Key thematic axes to prepare for**", ""]
        for index, axis in enumerate(model.thematic_axes, start=1):
            lines.append(f"{index}. **{axis.title or 'Axis'}**")
            lines += _bullets(axis.points, indent=1)
    for heading, items in (
        ("Risk landscape for preparation", model.risk_landscape),
        ("Methodology stance", model.methodology_stance),
        ("Historical context", model.historical_context),
        ("Open questions for the opening meeting", model.open_questions),
    ):
        if items:
            lines += ["", f"**{heading}**", "", *_bullets(items)]
    return lines


def briefing_markdown(model: Briefing) -> str:
    """Render a briefing model on its own — used by the stage's live preview."""
    return "\n".join(_briefing_md(model)).strip()


_RENDERERS = {
    "mission_metadata": _metadata_md,
    "scope_understanding": _scope_md,
    "risk_events": _risk_events_md,
    "methodology": _methodology_md,
    "historical_recommendations": _recommendations_md,
    "briefing": _briefing_md,
}


def stage_markdown(run: StageRun) -> str:
    """Render one stage's effective payload as markdown."""
    if not run.has_result:
        return _NOT_RUN
    renderer = _RENDERERS.get(run.key)
    if renderer is None:  # pragma: no cover - every stage has a renderer
        return f"```json\n{json.dumps(run.payload, indent=2, ensure_ascii=False)}\n```"
    lines = renderer(run.parsed())
    return "\n".join(lines).strip() or _NOT_RUN


# ---------------------------------------------------------------------------
# Whole-session exports
# ---------------------------------------------------------------------------


def _status_note(run: StageRun) -> str:
    bits = [run.status.label]
    if run.edited:
        bits.append("edited by analyst")
    if run.stale:
        bits.append("STALE — upstream changed after this ran")
    if run.review_note:
        bits.append(f"note: {run.review_note}")
    return " · ".join(bits)


def session_to_markdown(session: MissionSession, *, include_all_stages: bool = True) -> str:
    """The full pre-mission pack, or just the briefing when ``include_all_stages`` is False."""
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    metadata = session.stage("mission_metadata").parsed()
    title = getattr(metadata, "mission_name", None) or session.mission_id

    lines = [
        f"# Pre-mission briefing — {session.mission_id}",
        "",
        f"**{title}**",
        "",
        f"> Prepared with the internal-audit mission-preparation agent on {generated}  ",
        f"> Analyst: {session.analyst} · Backend: {session.backend_mode} · "
        f"{session.approved_count}/{len(STAGES)} stages approved",
        "",
    ]

    if session.stale_stages:
        stale = ", ".join(get_stage(k).title for k in session.stale_stages)
        lines += [
            f"> ⚠️ **Stale stages at export time:** {stale}. An upstream stage was changed "
            "after these ran; re-run them before relying on this pack.",
            "",
        ]

    stages = STAGES if include_all_stages else tuple(s for s in STAGES if s.key == "briefing")
    for spec in stages:
        run = session.stage(spec.key)
        lines += [
            "---",
            "",
            f"## {spec.title}",
            "",
            f"_{_status_note(run)}_",
            "",
            stage_markdown(run),
            "",
        ]

    lines += _provenance_md(session)
    return "\n".join(lines).rstrip() + "\n"


def _approved_unchanged(session: MissionSession) -> int:
    return sum(
        1
        for run in session.stages.values()
        if run.status is StageStatus.APPROVED and not run.edited
    )


def _provenance_md(session: MissionSession) -> list[str]:
    edited = [get_stage(k).title for k in session.stages if session.stage(k).edited]
    lines = [
        "---",
        "",
        "## Provenance",
        "",
        f"- Stages produced by the agent and approved unchanged: "
        f"{_approved_unchanged(session)}",
        f"- Stages amended by the analyst: {len(edited)}"
        + (f" ({', '.join(edited)})" if edited else ""),
        "",
        "| Time (UTC) | Actor | Action | Stage | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for event in session.audit_trail:
        stage_title = get_stage(event.stage).short_label if event.stage else "—"
        detail = (event.detail or "—").replace("|", "\\|")
        lines.append(
            f"| {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')} | {event.actor} | "
            f"{event.action} | {stage_title} | {detail} |"
        )
    return lines


def session_to_json(session: MissionSession) -> str:
    """Complete machine-readable record, including AI vs analyst payloads."""
    document = {
        "export_version": 1,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **session.to_dict(),
    }
    return json.dumps(document, indent=2, ensure_ascii=False, default=str)


def export_filename(session: MissionSession, extension: str) -> str:
    safe_id = session.mission_id.replace("/", "-").replace(" ", "_")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return f"premission_{safe_id}_{stamp}.{extension}"
