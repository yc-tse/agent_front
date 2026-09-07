"""Stage orchestration: what actually happens when the analyst presses Run.

Streamlit-free on purpose — the interesting behaviour (dependency handling,
error capture, draft runs) is testable without spinning up a UI.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .client import AuditAgentClient, BackendError
from .pipeline import STAGE_KEYS, StageSpec, get_stage
from .state import MissionSession, StageRun, StageStatus

ProgressCallback = Callable[[StageSpec], None]


def run_stage(
    session: MissionSession,
    client: AuditAgentClient,
    spec: StageSpec,
    *,
    feedback: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> StageRun:
    """Execute one stage and fold the outcome into the session.

    Never raises: a backend failure becomes an ERROR state carrying a message
    the analyst can act on, because a half-finished pipeline that explains
    itself beats a stack trace on a blank page.
    """
    run = session.stage(spec.key)
    session.start_run(spec.key)
    if feedback:
        run.feedback = feedback
        session.record("rerun_requested", stage=spec.key, detail=feedback)

    try:
        response = client.run_stage(
            spec,
            session.mission_id,
            session.context_for(spec),
            feedback=feedback,
            overrides=overrides,
        )
    except BackendError as exc:
        session.fail_run(spec.key, str(exc))
        return run
    except Exception as exc:  # defensive: never let the UI die on an unexpected shape
        session.fail_run(spec.key, f"Unexpected client error — {type(exc).__name__}: {exc}")
        return run

    session.complete_run(
        spec.key,
        response.payload,
        warnings=response.warnings,
        trace_id=response.trace_id,
    )
    return run


def runnable_in_draft(session: MissionSession, spec: StageSpec) -> bool:
    """Draft mode only needs upstream *results*, not upstream approval."""
    return all(session.stage(dep).has_result for dep in spec.depends_on)


def run_draft_pipeline(
    session: MissionSession,
    client: AuditAgentClient,
    *,
    on_progress: ProgressCallback | None = None,
    stop_on_error: bool = True,
) -> list[str]:
    """Run every outstanding stage back to back, leaving all of them for review.

    Nothing is auto-approved. The analyst still walks every checkpoint; this
    only removes the waiting between them. The audit trail records that the
    stages ran unattended, so the distinction survives into the export.
    """
    session.record("draft_run_started", detail="unattended run of outstanding stages")
    completed: list[str] = []

    for key in STAGE_KEYS:
        spec = get_stage(key)
        run = session.stage(key)
        if run.status is StageStatus.APPROVED and not run.stale:
            continue
        if run.has_result and not run.stale and run.status is StageStatus.REVIEW:
            continue  # already produced, waiting on a human — do not re-run
        if not runnable_in_draft(session, spec):
            break

        if on_progress:
            on_progress(spec)
        run_stage(session, client, spec)
        if session.stage(key).status is StageStatus.ERROR:
            if stop_on_error:
                break
            continue
        completed.append(key)

    session.record(
        "draft_run_finished",
        detail=f"{len(completed)} stage(s) produced, all awaiting review",
    )
    return completed
