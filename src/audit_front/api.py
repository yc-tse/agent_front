"""The backend integration surface: one method per backend API.

**This is the file to read before wiring the real backend.**

The mission-preparation agent exposes six sub-components. Rather than funnel
them through a single generic call, :class:`BackendAPI` gives each one a named
method, so connecting the real thing is six independent, greppable edits
instead of one conditional:

| Stage | Method |
|---|---|
| 1. Mission metadata | :meth:`BackendAPI.fetch_mission_metadata` |
| 2. Mission scope understanding | :meth:`BackendAPI.analyse_mission_scope` |
| 3. Operational risk events in scope | :meth:`BackendAPI.fetch_risk_events` |
| 4. Methodology references | :meth:`BackendAPI.fetch_methodology` |
| 5. Historical recommendations | :meth:`BackendAPI.fetch_historical_recommendations` |
| 6. Consolidated pre-mission briefing | :meth:`BackendAPI.build_briefing` |

Two implementations ship today:

* :class:`~audit_front.client.HttpBackendAPI` — the real one. Each of the six
  methods carries the endpoint it will call and a marked block to replace when
  that endpoint's true shape is known.
* :class:`~audit_front.example_data.ExampleDataAPI` — loads bundled JSON.

They can be mixed per stage (see :class:`~audit_front.routing.StageRouter`),
so backend endpoints can be switched on one at a time as they ship.

Every method takes a :class:`StageRequest` and returns a :class:`StageResponse`.
Nothing above this layer knows which implementation answered.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .pipeline import StageSpec


class BackendError(RuntimeError):
    """Any failure to obtain a usable stage payload.

    Carries enough context for the UI to show something an analyst can act on
    (and quote in a ticket) rather than a bare stack trace.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: str | None = None,
        trace_id: str | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail
        self.trace_id = trace_id
        self.url = url

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.append(f"HTTP {self.status_code}")
        if self.detail:
            parts.append(self.detail)
        if self.trace_id:
            parts.append(f"trace {self.trace_id}")
        return " · ".join(parts)


class StageNotImplementedError(BackendError):
    """Raised by a placeholder that has no data source wired up yet.

    Distinct from a backend outage: the UI can tell the analyst that *this
    endpoint is not connected yet*, which during a staged cutover is the more
    likely explanation.
    """

    def __init__(self, stage: StageSpec, hint: str | None = None) -> None:
        super().__init__(
            f"No data source is connected for “{stage.label}”",
            status_code=501,
            detail=hint
            or (
                f"Implement {stage.api_method}() on the live backend, or route this stage "
                "to example data from the sidebar's Connection panel."
            ),
        )
        self.stage = stage


@dataclass
class StageResponse:
    """Normalised result of one stage call."""

    payload: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    trace_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    """Which implementation answered — ``"live"`` or ``"example"``.

    Surfaced in the UI and the export, so a briefing assembled partly from
    example data can never be mistaken for a fully live one.
    """


@dataclass
class HealthReport:
    ok: bool
    detail: str
    latency_ms: float | None = None
    version: str | None = None


@dataclass(frozen=True)
class StageRequest:
    """Everything one backend call needs.

    A single object rather than five positional arguments, so adding a field
    later does not ripple through six method signatures and two
    implementations.
    """

    mission_id: str
    stage: StageSpec
    context: dict[str, Any] = field(default_factory=dict)
    """Analyst-validated payloads of this stage's dependencies, keyed by stage.

    This is the human-in-the-loop channel: an entity filter narrowed in the UI
    arrives here as the input to the next stage, not merely as display state.
    """

    feedback: str | None = None
    """A re-run instruction the analyst typed, if any."""

    overrides: dict[str, Any] | None = None
    analyst: str = "unknown"

    # -- convenience accessors, so implementations don't dig through dicts --

    @property
    def stage_key(self) -> str:
        return self.stage.key

    def upstream(self, stage_key: str) -> dict[str, Any]:
        """The validated payload of an upstream stage, or ``{}``."""
        value = self.context.get(stage_key)
        return value if isinstance(value, dict) else {}

    @property
    def metadata(self) -> dict[str, Any]:
        return self.upstream("mission_metadata")

    @property
    def scope(self) -> dict[str, Any]:
        return self.upstream("scope_understanding")

    @property
    def entity_filter(self) -> list[str]:
        """The perimeter as the analyst left it, falling back to the metadata."""
        scope = self.scope
        entities = scope.get("entity_filter") or scope.get("entities") or []
        if not entities:
            entities = self.metadata.get("entities") or []
        return [str(entity) for entity in entities]

    def to_json(self) -> dict[str, Any]:
        """The JSON body sent for a stage call.

        Kept here rather than in the HTTP client so every implementation — and
        every test — agrees on what a stage request *is*.
        """
        body: dict[str, Any] = {
            "mission_id": self.mission_id,
            "stage": self.stage_key,
            "context": self.context,
            "requested_by": self.analyst,
        }
        if self.feedback:
            body["analyst_feedback"] = self.feedback
        if self.overrides:
            body["overrides"] = self.overrides
        return body


class BackendAPI(ABC):
    """One method per backend sub-component.

    Subclasses implement the six abstract methods. ``run_stage`` is the
    dispatcher the rest of the app calls; it resolves the method from
    ``StageSpec.api_method`` and should not be overridden except by a router.
    """

    label: ClassVar[str] = "backend"
    """Short name shown in the UI: ``"live"``, ``"example"``, ``"mixed"``."""

    # -- the six backend APIs ---------------------------------------------

    @abstractmethod
    def fetch_mission_metadata(self, request: StageRequest) -> StageResponse:
        """Stage 1 — the mission's identity as held in the audit tooling.

        The only stage with no upstream context: it runs from the mission code
        alone. Expected payload: name, brief scope, countries, entities, risk
        families, the activity tree and business lines.
        """

    @abstractmethod
    def analyse_mission_scope(self, request: StageRequest) -> StageResponse:
        """Stage 2 — which dimension defines the perimeter, and the filter set.

        Reads ``request.metadata``. Expected payload: the primary scope driver,
        coverage, missing dimensions, the filters, and the reasoning behind them.
        """

    @abstractmethod
    def fetch_risk_events(self, request: StageRequest) -> StageResponse:
        """Stage 3 — operational-loss events on the validated perimeter.

        Reads ``request.scope`` / ``request.entity_filter``. An empty result is
        a legitimate answer, not an error.
        """

    @abstractmethod
    def fetch_methodology(self, request: StageRequest) -> StageResponse:
        """Stage 4 — registered audit methodology ("methodo") for this scope.

        Reads ``request.scope``. "Nothing registered" is the common answer and
        must come back as a payload, not an exception.
        """

    @abstractmethod
    def fetch_historical_recommendations(self, request: StageRequest) -> StageResponse:
        """Stage 5 — recommendations issued on this perimeter in earlier cycles.

        Reads ``request.scope``. As with stage 4, an empty result is normal.
        """

    @abstractmethod
    def build_briefing(self, request: StageRequest) -> StageResponse:
        """Stage 6 — synthesis of every validated stage into the deliverable.

        Reads the whole of ``request.context``: metadata, scope, risk events,
        methodology and historical recommendations, each as the analyst
        approved it.
        """

    # -- shared plumbing ---------------------------------------------------

    def health(self) -> HealthReport:  # pragma: no cover - overridden by both
        return HealthReport(ok=True, detail=f"{self.label} backend")

    def source_of(self, stage: StageSpec) -> str:
        """Which implementation will answer for this stage — ``live``/``example``.

        Routers override this; a single-implementation backend answers for all
        six stages.
        """
        return self.label

    def run_stage(
        self,
        stage: StageSpec,
        mission_id: str,
        context: dict[str, Any],
        *,
        feedback: str | None = None,
        overrides: dict[str, Any] | None = None,
        analyst: str | None = None,
    ) -> StageResponse:
        """Dispatch to the method named by ``stage.api_method``.

        The single entry point used by :mod:`audit_front.runner`; everything
        above this layer stays unaware of which backend answered.
        """
        request = StageRequest(
            mission_id=mission_id,
            stage=stage,
            context=context or {},
            feedback=feedback,
            overrides=overrides,
            analyst=analyst or self._analyst(),
        )
        method = getattr(self, stage.api_method, None)
        if method is None:  # pragma: no cover - guarded by test_api_surface
            raise BackendError(
                f"{type(self).__name__} has no method {stage.api_method!r} "
                f"for stage {stage.key!r}"
            )
        response = method(request)
        if response.source == "unknown":
            response.source = self.source_of(stage)
        return response

    def _analyst(self) -> str:
        settings = getattr(self, "settings", None)
        return getattr(settings, "analyst", None) or "unknown"

    def close(self) -> None:
        """Release any resources. Safe to call more than once."""
        return None
