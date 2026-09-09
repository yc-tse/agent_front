"""The example backend: serves bundled JSON instead of calling anything.

**One mission is one file.** Everything about a sample mission — its id, its
name, and every stage payload from the metadata through to the briefing — lives
in a single document under ``example_data/``:

```json
{
  "mission_id": "26-IRB/AYVENS-019",
  "mission_name": "2026_Ayvens United Kingdom — …",
  "stages": {
    "mission_metadata": { … },
    "scope_understanding": { … },
    …
  }
}
```

Nothing about a mission is written in Python. The directory is scanned at
startup, so adding a sample mission means dropping a file in — no code, no
registration, no redeploy — and a mission file can be handed to someone,
version-controlled and diffed as one unit.

The filename is free: missions are keyed on the ``mission_id`` *inside* the
document, so ``ayvens-uk.json`` and ``26-IRB_AYVENS-019.json`` work equally
well.

It is also not a dumb fixture server: the stages that query the perimeter honour
``request.context``, so an entity filter narrowed by the analyst in stage 2
really does change what comes back. Without that, the human-in-the-loop
behaviour could not be demonstrated or tested offline.
"""

from __future__ import annotations

import copy
import json
import random
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from .api import BackendAPI, BackendError, HealthReport, StageRequest, StageResponse
from .config import Settings
from .pipeline import STAGE_KEYS

EXAMPLE_DIR = Path(__file__).resolve().parent / "example_data"

Transform = Callable[[dict[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------------
# Loading
#
# The directory is the registry. Nothing here names a mission.
# ---------------------------------------------------------------------------


def suggested_filename(mission_id: str) -> str:
    """A filesystem-safe filename for a mission id — used in error messages."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in mission_id.strip())
    return f"{safe or 'mission'}.json"


def _read_document(path: Path) -> dict[str, Any]:
    """Parse one mission file, failing with a message that names the file."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise BackendError(
            f"Example mission file {path.name} is not valid JSON",
            status_code=500,
            detail=str(exc),
        ) from exc
    except OSError as exc:  # pragma: no cover - unreadable file
        raise BackendError(
            f"Example mission file {path.name} could not be read",
            status_code=500,
            detail=str(exc),
        ) from exc
    if not isinstance(document, dict):
        raise BackendError(
            f"Example mission file {path.name} must contain a JSON object",
            status_code=500,
            detail='Expected {"mission_id": …, "mission_name": …, "stages": {…}}.',
        )
    return document


@lru_cache(maxsize=1)
def _scan() -> tuple[dict[str, Path], dict[str, str]]:
    """Scan the example directory once: (mission id -> file, skipped file -> why).

    Missions are keyed on the ``mission_id`` *inside* each document rather than
    on the filename, so files can be named however suits the person adding
    them. A file that cannot be read, or that carries no mission id, is skipped
    rather than taking the whole app down — but it is *remembered*, because a
    broken file that vanishes silently is the kind of thing that costs an
    afternoon.
    """
    index: dict[str, Path] = {}
    skipped: dict[str, str] = {}
    if not EXAMPLE_DIR.is_dir():  # pragma: no cover - packaging accident
        return index, skipped
    for path in sorted(EXAMPLE_DIR.glob("*.json")):
        try:
            document = _read_document(path)
        except BackendError as exc:
            skipped[path.name] = exc.message
            continue
        mission_id = str(document.get("mission_id") or "").strip()
        if not mission_id:
            skipped[path.name] = 'no "mission_id" field'
            continue
        index.setdefault(mission_id.upper(), path)
    return index, skipped


def _index() -> dict[str, Path]:
    return _scan()[0]


def skipped_files() -> dict[str, str]:
    """Files in the example directory that could not be used, and why."""
    return dict(_scan()[1])


def reload_example_data() -> None:
    """Re-scan the directory — call after adding or renaming a mission file."""
    _scan.cache_clear()


def mission_file(mission_id: str) -> Path | None:
    """The file backing a mission id, or None when nothing matches."""
    return _index().get(mission_id.strip().upper())


def load_mission(mission_id: str) -> dict[str, Any]:
    """The whole mission document, re-read from disk on every call.

    Deliberately not cached: editing a mission file while the app is running
    takes effect on the next run, which is the point of keeping the examples
    in data rather than in code.
    """
    path = mission_file(mission_id)
    if path is None:
        known = ", ".join(sorted(_index())) or "none"
        detail = (
            f"Bundled missions: {known}. Add "
            f"src/audit_front/example_data/{suggested_filename(mission_id)} with "
            '{"mission_id", "mission_name", "stages"}, or switch the stage to the '
            "live backend."
        )
        # Name the unusable files too: "no missions" when a file is sitting
        # right there, broken, is a maddening thing to debug.
        skipped = skipped_files()
        if skipped:
            listed = "; ".join(f"{name} ({why})" for name, why in sorted(skipped.items()))
            detail += f" Ignored file(s) in that directory: {listed}."
        raise BackendError(
            f"Mission {mission_id!r} has no example data",
            status_code=404,
            detail=detail,
        )
    return _read_document(path)


def available_missions() -> list[tuple[str, str]]:
    """(mission_id, mission_name) for every bundled example mission."""
    missions: list[tuple[str, str]] = []
    for path in _index().values():
        try:
            document = _read_document(path)
        except BackendError:  # pragma: no cover - file broke since the scan
            continue
        mission_id = str(document.get("mission_id", "")).strip()
        missions.append((mission_id, str(document.get("mission_name", "")).strip()))
    return sorted(missions)


def load_payload(mission_id: str, stage_key: str) -> dict[str, Any]:
    """The example payload for one stage, or a message saying how to add it."""
    document = load_mission(mission_id)
    stages = document.get("stages")
    if not isinstance(stages, dict):
        raise BackendError(
            f"Example mission {mission_id} has no 'stages' object",
            status_code=500,
            detail=(
                f"Expected a \"stages\" key mapping stage names to payloads in "
                f"{suggested_filename(mission_id)}."
            ),
        )
    payload = stages.get(stage_key)
    if payload is None:
        raise BackendError(
            f"No example data for stage {stage_key!r} in mission {mission_id}",
            status_code=501,
            detail=(
                f'Add a "{stage_key}" entry under "stages" in '
                f"{mission_file(mission_id).name} — a captured backend response works as-is."
            ),
        )
    if not isinstance(payload, dict):
        payload = {"items": payload}
    return copy.deepcopy(payload)


# ---------------------------------------------------------------------------
# Context-aware derivations
#
# These are what make the example backend honest: the analyst's validated
# perimeter genuinely changes what the downstream stages return.
# ---------------------------------------------------------------------------


def filter_to_perimeter(
    payload: dict[str, Any], request: StageRequest, list_key: str
) -> dict[str, Any]:
    """Drop records whose entity fell outside the analyst-validated perimeter."""
    allowed = {entity.upper() for entity in request.entity_filter}
    if not allowed:
        return payload
    records = payload.get(list_key) or []
    kept = [
        record
        for record in records
        if str(record.get("entity", "")).upper() in allowed or not record.get("entity")
    ]
    if len(kept) == len(records):
        return payload

    out = dict(payload)
    out[list_key] = kept
    dropped = len(records) - len(kept)
    notes = [f"{dropped} record(s) excluded: entity outside the validated perimeter."]
    commentary = "interpretation" if list_key == "events" else "implications"

    if list_key == "events":
        out["total_count"] = len(kept)
        out["total_amount"] = sum(float(r.get("gross_amount") or 0) for r in kept)
    elif list_key == "reports":
        notes += _resync_report_synthesis(payload, out, records, kept)

    out[commentary] = [*payload.get(commentary, []), *notes]
    return out


def _resync_report_synthesis(
    payload: dict[str, Any],
    out: dict[str, Any],
    records: list[dict[str, Any]],
    kept: list[dict[str, Any]],
) -> list[str]:
    """Keep the cross-report synthesis honest when reports leave the perimeter.

    The key messages and IGAD positions are drawn *from* the reports, so once
    some are excluded the synthesis can cite a report that is no longer there —
    which is exactly the kind of quiet inconsistency this tool exists to stop.
    Positions naming a dropped report go; the rest is flagged as predating the
    exclusion rather than silently rewritten.
    """
    if not kept:
        out["key_messages"] = []
        out["igad_positions"] = []
        return ["Cross-report synthesis dropped: no reports remain in the perimeter."]

    kept_ids = {str(r.get("report_id") or "") for r in kept}
    dropped_ids = {str(r.get("report_id") or "") for r in records} - kept_ids - {""}
    if not dropped_ids:
        return []

    positions = payload.get("igad_positions") or []
    surviving = [p for p in positions if not any(ref in str(p) for ref in dropped_ids)]
    notes: list[str] = []
    if len(surviving) != len(positions):
        out["igad_positions"] = surviving
        notes.append(
            f"{len(positions) - len(surviving)} IGAD position(s) dropped: they cite "
            f"{', '.join(sorted(dropped_ids))}, now outside the perimeter."
        )
    if payload.get("key_messages"):
        notes.append(
            "The cross-report key messages were written before that exclusion — re-read "
            "them against the reports that remain."
        )
    return notes


def rebuild_briefing(payload: dict[str, Any], request: StageRequest) -> dict[str, Any]:
    """Re-derive the briefing sections that depend on validated upstream stages."""
    out = dict(payload)
    entities = request.entity_filter
    if entities:
        out["perimeter"] = entities

    risk_events = request.upstream("risk_events")
    events = risk_events.get("events") or []
    if events:
        total = sum(float(e.get("gross_amount") or 0) for e in events)
        open_events = [e for e in events if str(e.get("status", "")).lower() == "open"]
        out["risk_landscape"] = [
            f"{len(events)} operational loss event(s) in the validated perimeter, "
            f"{total:,.0f} gross.",
            f"{len(open_events)} still open — confirm remediation status before fieldwork.",
            *[str(item) for item in risk_events.get("interpretation", [])],
        ]

    # Historical context is assembled from two stages: prior 3LOD reporting
    # (what was said) and prior recommendations (what was asked for).
    history: list[str] = []

    reports_payload = request.upstream("historical_reports")
    reports = reports_payload.get("reports") or []
    if reports:
        lines_covered = sorted(
            {str(r.get("line_of_defence") or "Unspecified") for r in reports}
        )
        history.append(
            f"{len(reports)} prior report(s) cover this perimeter "
            f"({', '.join(lines_covered)})."
        )
        history += [
            f"{r.get('report_id', '?')} — {r.get('title', '')}"
            + (f" ({r.get('rating')})" if r.get("rating") else "")
            for r in reports
        ]
        positions = reports_payload.get("igad_positions") or [
            f"{r.get('report_id', '?')}: {r.get('igad_position')}"
            for r in reports
            if r.get("igad_position")
        ]
        if positions:
            history.append("IGAD positions on record:")
            history += [str(position) for position in positions]

    recommendations = request.upstream("historical_recommendations").get("recommendations") or []
    if recommendations:
        closed = {"closed", "done", "implemented", "cancelled"}
        still_open = [r for r in recommendations if str(r.get("status", "")).lower() not in closed]
        history.append(
            f"{len(recommendations)} prior recommendation(s) touch this perimeter; "
            f"{len(still_open)} open."
        )
        history += [
            f"{r.get('rec_id', '?')} — {r.get('title', '')} ({r.get('status', 'unknown')})"
            for r in recommendations
        ]

    if history:
        out["historical_context"] = history

    methodology = request.upstream("methodology")
    references = methodology.get("references") or []
    if references:
        out["methodology_stance"] = [
            f"Registered methodology available: {r.get('ref_id', '')} — {r.get('title', '')}"
            for r in references
        ] + [str(item) for item in methodology.get("recommended_approach", [])]
    return out


# ---------------------------------------------------------------------------
# The API implementation
# ---------------------------------------------------------------------------


class ExampleDataAPI(BackendAPI):
    """Serves the bundled JSON. Same methods as the live backend."""

    label = "example"

    def __init__(self, settings: Settings | None = None, *, latency: bool = True) -> None:
        self.settings = settings
        self._latency = latency
        self._counter = 0

    def health(self) -> HealthReport:
        return HealthReport(
            ok=True,
            detail=(
                f"Example data — {len(_index())} mission file(s) in "
                f"{EXAMPLE_DIR.name}/, no network calls"
            ),
            latency_ms=0.0,
            version="example",
        )

    # -- the backend APIs -------------------------------------------------

    def fetch_mission_metadata(self, request: StageRequest) -> StageResponse:
        return self._serve(request)

    def analyse_mission_scope(self, request: StageRequest) -> StageResponse:
        return self._serve(request)

    def fetch_risk_events(self, request: StageRequest) -> StageResponse:
        # Narrowing the perimeter in stage 2 must narrow the losses here.
        return self._serve(request, lambda p: filter_to_perimeter(p, request, "events"))

    def fetch_methodology(self, request: StageRequest) -> StageResponse:
        return self._serve(request)

    def fetch_historical_reports(self, request: StageRequest) -> StageResponse:
        return self._serve(request, lambda p: filter_to_perimeter(p, request, "reports"))

    def fetch_historical_recommendations(self, request: StageRequest) -> StageResponse:
        return self._serve(request, lambda p: filter_to_perimeter(p, request, "recommendations"))

    def build_briefing(self, request: StageRequest) -> StageResponse:
        return self._serve(request, lambda p: rebuild_briefing(p, request))

    # -- internals ---------------------------------------------------------

    def _serve(self, request: StageRequest, transform: Transform | None = None) -> StageResponse:
        if self._latency:
            time.sleep(random.uniform(0.5, 1.3))

        payload = load_payload(request.mission_id, request.stage_key)
        if transform is not None:
            payload = transform(payload)

        warnings: list[str] = []
        if request.feedback:
            # Mirrors how a re-run reaches the agent: the instruction shows up in
            # the output, so the analyst can confirm it was taken into account.
            note = f"Re-run with analyst instruction: {request.feedback}"
            for key in ("reasoning", "interpretation", "implications"):
                if isinstance(payload.get(key), list):
                    payload[key] = [*payload[key], note]
                    break
            else:
                warnings.append(note)

        if request.overrides:
            payload.update(request.overrides)

        self._counter += 1
        slug = request.mission_id.split("/")[-1].lower()
        return StageResponse(
            payload=payload,
            warnings=warnings,
            trace_id=f"example-{slug}-{request.stage_key}-{self._counter:03d}",
            raw={"status": "completed", "data": payload},
        )


def missing_stages(mission_id: str) -> list[str]:
    """Stages this mission document has no payload for."""
    if mission_file(mission_id) is None:
        return list(STAGE_KEYS)
    stages = load_mission(mission_id).get("stages")
    if not isinstance(stages, dict):
        return list(STAGE_KEYS)
    return [key for key in STAGE_KEYS if key not in stages]
