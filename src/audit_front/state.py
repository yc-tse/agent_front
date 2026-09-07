"""Session state: what has run, what the analyst changed, and in what order.

Deliberately free of Streamlit imports so it can be unit-tested and reused.
`ui/session.py` binds an instance of :class:`MissionSession` into
``st.session_state``.

Two ideas carry the whole human-in-the-loop design:

* **AI output and analyst output are stored separately.** ``ai_payload`` is
  never overwritten by an edit; ``analyst_payload`` holds the override. The
  export and the audit trail can therefore always answer "what did the agent
  say, and what did the human change?" — which is the question an audit
  department will be asked about an AI-assisted deliverable.
* **Editing a stage marks its dependants stale**, rather than silently
  leaving a briefing built on a perimeter that no longer holds.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .pipeline import STAGE_KEYS, StageSpec, downstream_of, get_stage


def _now() -> datetime:
    return datetime.now(UTC)


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    REVIEW = "review"  # agent produced output, awaiting analyst validation
    APPROVED = "approved"
    ERROR = "error"

    @property
    def label(self) -> str:
        return {
            StageStatus.PENDING: "Not run",
            StageStatus.RUNNING: "Running",
            StageStatus.REVIEW: "Awaiting review",
            StageStatus.APPROVED: "Approved",
            StageStatus.ERROR: "Failed",
        }[self]

    @property
    def icon(self) -> str:
        return {
            StageStatus.PENDING: "○",
            StageStatus.RUNNING: "◐",
            StageStatus.REVIEW: "◆",
            StageStatus.APPROVED: "●",
            StageStatus.ERROR: "✕",
        }[self]

    @property
    def color(self) -> str:
        return {
            StageStatus.PENDING: "#9AA0A6",
            StageStatus.RUNNING: "#1A73E8",
            StageStatus.REVIEW: "#E8830C",
            StageStatus.APPROVED: "#1E8E3E",
            StageStatus.ERROR: "#D93025",
        }[self]


@dataclass
class AuditEvent:
    """One line of the provenance record."""

    timestamp: datetime
    actor: str  # analyst login, or "agent"
    action: str
    stage: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(timespec="seconds"),
            "actor": self.actor,
            "action": self.action,
            "stage": self.stage,
            "detail": self.detail,
        }


@dataclass
class StageRun:
    """State of a single stage across runs, edits and approval."""

    key: str
    status: StageStatus = StageStatus.PENDING
    ai_payload: dict[str, Any] | None = None
    analyst_payload: dict[str, Any] | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    trace_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_s: float | None = None
    feedback: str | None = None  # instructions given for the most recent re-run
    review_note: str | None = None  # analyst comment recorded at approval
    stale: bool = False  # an upstream stage changed after this one ran
    run_count: int = 0
    source: str | None = None
    """Which backend answered — ``"live"`` or ``"example"``.

    Recorded per stage because the six APIs go live at different times: a pack
    can legitimately mix the two, and the reader has to be able to tell.
    """

    @property
    def is_example_data(self) -> bool:
        return self.source == "example"

    @property
    def payload(self) -> dict[str, Any]:
        """What downstream stages and the export consume: the analyst's version."""
        if self.analyst_payload is not None:
            return self.analyst_payload
        return self.ai_payload or {}

    @property
    def edited(self) -> bool:
        return self.analyst_payload is not None

    @property
    def has_result(self) -> bool:
        return self.ai_payload is not None or self.analyst_payload is not None

    @property
    def spec(self) -> StageSpec:
        return get_stage(self.key)

    def parsed(self) -> Any:
        """Parse the effective payload with this stage's model.

        Returns an empty model instance rather than raising: a malformed
        payload should degrade to "nothing to show here" plus the raw JSON
        view, never to a broken page.
        """
        model = self.spec.model
        try:
            return model.model_validate(self.payload)
        except Exception:
            return model()

    def parsed_ai(self) -> Any:
        model = self.spec.model
        try:
            return model.model_validate(self.ai_payload or {})
        except Exception:
            return model()

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.key,
            "status": self.status.value,
            "edited_by_analyst": self.edited,
            "stale": self.stale,
            "run_count": self.run_count,
            "source": self.source,
            "duration_s": self.duration_s,
            "trace_id": self.trace_id,
            "error": self.error,
            "warnings": list(self.warnings),
            "feedback": self.feedback,
            "review_note": self.review_note,
            "started_at": (
                self.started_at.isoformat(timespec="seconds") if self.started_at else None
            ),
            "ai_payload": self.ai_payload,
            "analyst_payload": self.analyst_payload,
        }


@dataclass
class MissionSession:
    """Everything known about one mission-preparation run."""

    mission_id: str
    analyst: str = "unknown"
    backend_mode: str = "mock"
    created_at: datetime = field(default_factory=_now)
    stages: dict[str, StageRun] = field(default_factory=dict)
    audit_trail: list[AuditEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        for key in STAGE_KEYS:
            self.stages.setdefault(key, StageRun(key=key))

    # -- provenance --------------------------------------------------------

    def record(
        self,
        action: str,
        *,
        stage: str | None = None,
        detail: str | None = None,
        actor: str | None = None,
    ) -> None:
        self.audit_trail.append(
            AuditEvent(
                timestamp=_now(),
                actor=actor or self.analyst,
                action=action,
                stage=stage,
                detail=detail,
            )
        )

    # -- stage access ------------------------------------------------------

    def stage(self, key: str) -> StageRun:
        return self.stages[key]

    def status_of(self, key: str) -> StageStatus:
        return self.stages[key].status

    # -- transitions -------------------------------------------------------

    def start_run(self, key: str) -> None:
        run = self.stages[key]
        run.status = StageStatus.RUNNING
        run.started_at = _now()
        run.error = None
        self.record("stage_run_started", stage=key, actor="agent")

    def complete_run(
        self,
        key: str,
        payload: dict[str, Any],
        *,
        warnings: list[str] | None = None,
        trace_id: str | None = None,
        source: str | None = None,
    ) -> None:
        run = self.stages[key]
        run.ai_payload = payload
        run.analyst_payload = None  # a fresh agent run supersedes prior edits
        run.status = StageStatus.REVIEW
        run.warnings = list(warnings or [])
        run.trace_id = trace_id
        run.source = source
        run.finished_at = _now()
        run.stale = False
        run.run_count += 1
        if run.started_at:
            run.duration_s = (run.finished_at - run.started_at).total_seconds()
        self.record(
            "stage_completed",
            stage=key,
            actor="agent",
            detail=" · ".join(
                part
                for part in (
                    f"run #{run.run_count}",
                    f"source {source}" if source else None,
                    f"trace {trace_id}" if trace_id else None,
                )
                if part
            ),
        )

    def fail_run(self, key: str, message: str) -> None:
        run = self.stages[key]
        run.status = StageStatus.ERROR
        run.error = message
        run.finished_at = _now()
        self.record("stage_failed", stage=key, actor="agent", detail=message)

    def apply_edit(self, key: str, payload: dict[str, Any], *, detail: str | None = None) -> None:
        """Store an analyst override and invalidate everything downstream."""
        run = self.stages[key]
        run.analyst_payload = copy.deepcopy(payload)
        if run.status is StageStatus.APPROVED:
            run.status = StageStatus.REVIEW
        self.record("stage_edited", stage=key, detail=detail)
        self._mark_downstream_stale(key)

    def revert_edit(self, key: str) -> None:
        run = self.stages[key]
        run.analyst_payload = None
        self.record("stage_edit_reverted", stage=key)
        self._mark_downstream_stale(key)

    def approve(self, key: str, note: str | None = None) -> None:
        run = self.stages[key]
        run.status = StageStatus.APPROVED
        run.review_note = note or None
        run.stale = False
        self.record(
            "stage_approved",
            stage=key,
            detail=("edited then approved" if run.edited else "approved as produced")
            + (f" — {note}" if note else ""),
        )

    def reopen(self, key: str) -> None:
        run = self.stages[key]
        if run.has_result:
            run.status = StageStatus.REVIEW
        self.record("stage_reopened", stage=key)

    def _mark_downstream_stale(self, key: str) -> None:
        affected = [s.key for s in downstream_of(key) if self.stages[s.key].has_result]
        for stage_key in affected:
            self.stages[stage_key].stale = True
        if affected:
            self.record(
                "downstream_invalidated",
                stage=key,
                detail="now stale: " + ", ".join(affected),
            )

    # -- queries the UI needs ---------------------------------------------

    def context_for(self, spec: StageSpec) -> dict[str, Any]:
        """Approved upstream payloads, as sent to the backend for this stage."""
        return {
            dep: self.stages[dep].payload
            for dep in spec.depends_on
            if self.stages[dep].has_result
        }

    def blocking_reason(self, spec: StageSpec) -> str | None:
        """Why this stage cannot run yet, or None when it can."""
        missing = [
            get_stage(dep).title
            for dep in spec.depends_on
            if self.stages[dep].status is not StageStatus.APPROVED
        ]
        if not missing:
            return None
        if len(missing) == 1:
            return f"Approve “{missing[0]}” first."
        return "Approve these first: " + "; ".join(missing) + "."

    def can_run(self, spec: StageSpec) -> bool:
        return self.blocking_reason(spec) is None

    def next_runnable(self) -> StageSpec | None:
        """First stage that has no result yet and whose dependencies are approved."""
        for key in STAGE_KEYS:
            spec = get_stage(key)
            run = self.stages[key]
            if run.status in (StageStatus.PENDING, StageStatus.ERROR) and self.can_run(spec):
                return spec
        return None

    def next_actionable(self) -> StageSpec | None:
        """Where the analyst's attention belongs: a review, a retry, or the next run."""
        for key in STAGE_KEYS:
            run = self.stages[key]
            if run.status in (StageStatus.REVIEW, StageStatus.ERROR) or run.stale:
                return get_stage(key)
        return self.next_runnable()

    @property
    def approved_count(self) -> int:
        return sum(1 for r in self.stages.values() if r.status is StageStatus.APPROVED)

    @property
    def is_complete(self) -> bool:
        return self.approved_count == len(STAGE_KEYS)

    @property
    def example_data_stages(self) -> list[str]:
        """Stages served from example data rather than the live backend."""
        return [k for k in STAGE_KEYS if self.stages[k].is_example_data]

    @property
    def stale_stages(self) -> list[str]:
        return [k for k in STAGE_KEYS if self.stages[k].stale]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "analyst": self.analyst,
            "backend_mode": self.backend_mode,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "approved_stages": self.approved_count,
            "total_stages": len(STAGE_KEYS),
            "complete": self.is_complete,
            "stages": {k: self.stages[k].to_dict() for k in STAGE_KEYS},
            "audit_trail": [e.to_dict() for e in self.audit_trail],
        }
