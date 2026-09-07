"""The example backend: serves bundled JSON instead of calling anything.

Every stage payload lives as a file under ``example_data/<mission>/<stage>.json``,
which makes this more than a demo fixture:

* **Capturing a real response is a drop-in.** Save what the backend actually
  returned as ``…/risk_events.json`` and the UI renders it immediately — no
  Python, no redeploy. That is the fastest way to check a new endpoint's shape
  against this front-end before wiring it up.
* **Non-developers can edit it.** Adding a sample mission means adding a folder.

It is also not a dumb fixture server: stages 3, 5 and 6 honour
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

AYVENS_UK = "26-IRB/AYVENS-019"
AYVENS_DE = "26-IRB/AYVENS-021"

Transform = Callable[[dict[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _folder_name(mission_id: str) -> str:
    return mission_id.replace("/", "_").replace(" ", "_")


@lru_cache(maxsize=1)
def _index() -> dict[str, Path]:
    """Map mission id -> folder, by reading each folder's metadata file.

    Keyed on the ``mission_id`` inside the file rather than on the folder name,
    so a folder can be named whatever is convenient on disk.
    """
    index: dict[str, Path] = {}
    if not EXAMPLE_DIR.is_dir():  # pragma: no cover - packaging accident
        return index
    for folder in sorted(p for p in EXAMPLE_DIR.iterdir() if p.is_dir()):
        metadata_file = folder / "mission_metadata.json"
        if not metadata_file.is_file():
            continue
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # pragma: no cover - malformed fixture
            continue
        mission_id = str(metadata.get("mission_id") or "").strip()
        if mission_id:
            index[mission_id.upper()] = folder
    return index


def available_missions() -> list[tuple[str, str]]:
    """(mission_id, mission_name) for every bundled example mission."""
    missions: list[tuple[str, str]] = []
    for folder in _index().values():
        metadata = _read(folder / "mission_metadata.json") or {}
        missions.append(
            (str(metadata.get("mission_id", "")), str(metadata.get("mission_name", "")))
        )
    return sorted(missions)


def _read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise BackendError(
            f"Example data file {path.name} is not valid JSON",
            status_code=500,
            detail=str(exc),
        ) from exc
    return payload if isinstance(payload, dict) else {"items": payload}


def load_payload(mission_id: str, stage_key: str) -> dict[str, Any]:
    """The example payload for one stage, or a message saying how to add it."""
    folder = _index().get(mission_id.strip().upper())
    if folder is None:
        known = ", ".join(sorted(_index())) or "none"
        raise BackendError(
            f"Mission {mission_id!r} has no example data",
            status_code=404,
            detail=(
                f"Bundled missions: {known}. Add "
                f"src/audit_front/example_data/{_folder_name(mission_id)}/ with one JSON "
                "file per stage, or switch the stage to the live backend."
            ),
        )
    payload = _read(folder / f"{stage_key}.json")
    if payload is None:
        raise BackendError(
            f"No example data for stage {stage_key!r} in mission {mission_id}",
            status_code=501,
            detail=(
                f"Add src/audit_front/example_data/{folder.name}/{stage_key}.json — "
                "a captured backend response works as-is."
            ),
        )
    return copy.deepcopy(payload)


# ---------------------------------------------------------------------------
# Context-aware derivations
#
# These are what make the example backend honest: the analyst's validated
# perimeter genuinely changes what stages 3, 5 and 6 return.
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
    note = f"{dropped} record(s) excluded: entity outside the validated perimeter."
    commentary = "interpretation" if list_key == "events" else "implications"
    out[commentary] = [*payload.get(commentary, []), note]
    if list_key == "events":
        out["total_count"] = len(kept)
        out["total_amount"] = sum(float(r.get("gross_amount") or 0) for r in kept)
    return out


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

    recommendations = request.upstream("historical_recommendations").get("recommendations") or []
    if recommendations:
        closed = {"closed", "done", "implemented", "cancelled"}
        still_open = [r for r in recommendations if str(r.get("status", "")).lower() not in closed]
        out["historical_context"] = [
            f"{len(recommendations)} prior recommendation(s) touch this perimeter; "
            f"{len(still_open)} open.",
            *[
                f"{r.get('rec_id', '?')} — {r.get('title', '')} ({r.get('status', 'unknown')})"
                for r in recommendations
            ],
        ]

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
    """Serves the bundled JSON. Same six methods as the live backend."""

    label = "example"

    def __init__(self, settings: Settings | None = None, *, latency: bool = True) -> None:
        self.settings = settings
        self._latency = latency
        self._counter = 0

    def health(self) -> HealthReport:
        return HealthReport(
            ok=True,
            detail=f"Example data — {len(_index())} bundled mission(s), no network calls",
            latency_ms=0.0,
            version="example",
        )

    # -- the six backend APIs ---------------------------------------------

    def fetch_mission_metadata(self, request: StageRequest) -> StageResponse:
        return self._serve(request)

    def analyse_mission_scope(self, request: StageRequest) -> StageResponse:
        return self._serve(request)

    def fetch_risk_events(self, request: StageRequest) -> StageResponse:
        # Narrowing the perimeter in stage 2 must narrow the losses here.
        return self._serve(request, lambda p: filter_to_perimeter(p, request, "events"))

    def fetch_methodology(self, request: StageRequest) -> StageResponse:
        return self._serve(request)

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
    """Stages this mission has no example file for — used by the health check."""
    folder = _index().get(mission_id.strip().upper())
    if folder is None:
        return list(STAGE_KEYS)
    return [key for key in STAGE_KEYS if not (folder / f"{key}.json").is_file()]
