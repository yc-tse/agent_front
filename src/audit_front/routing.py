"""Choosing, per stage, between the live backend and example data.

The backend APIs will not arrive at once. This router lets each one be
switched over the day it ships, without a branch or a redeploy: name the
stages that are live and the rest keep serving example data.

    AUDIT_LIVE_STAGES=mission_metadata,scope_understanding

Everything downstream still sees a single :class:`~audit_front.api.BackendAPI`.
The one thing that must never blur is *which* source answered — a briefing
assembled partly from example data cannot be allowed to look fully live — so
every response is stamped with its source, and that stamp reaches the stage
header, the audit trail and the export.
"""

from __future__ import annotations

from .api import BackendAPI, HealthReport, StageRequest, StageResponse
from .client import HttpBackendAPI
from .config import Settings
from .example_backend import ExampleDataAPI
from .pipeline import STAGE_KEYS, StageSpec, get_stage


class StageRouter(BackendAPI):
    """Delegates each stage to whichever backend is configured for it."""

    label = "mixed"

    def __init__(
        self,
        live: BackendAPI,
        example: BackendAPI,
        live_stages: frozenset[str],
        settings: Settings | None = None,
    ) -> None:
        self.live = live
        self.example = example
        self.live_stages = frozenset(live_stages)
        self.settings = settings

    # -- routing -----------------------------------------------------------

    def delegate_for(self, stage_key: str) -> BackendAPI:
        return self.live if stage_key in self.live_stages else self.example

    def source_of(self, stage: StageSpec) -> str:
        return self.delegate_for(stage.key).label

    def wiring(self) -> list[tuple[StageSpec, str]]:
        """(stage, source) for every stage — what the Connection panel renders."""
        return [(get_stage(key), self.source_of(get_stage(key))) for key in STAGE_KEYS]

    @property
    def is_uniform(self) -> bool:
        return not self.live_stages or self.live_stages == frozenset(STAGE_KEYS)

    # -- the backend APIs, one delegation each ----------------------------

    def fetch_mission_metadata(self, request: StageRequest) -> StageResponse:
        return self.delegate_for("mission_metadata").fetch_mission_metadata(request)

    def analyse_mission_scope(self, request: StageRequest) -> StageResponse:
        return self.delegate_for("scope_understanding").analyse_mission_scope(request)

    def fetch_risk_events(self, request: StageRequest) -> StageResponse:
        return self.delegate_for("risk_events").fetch_risk_events(request)

    def fetch_methodology(self, request: StageRequest) -> StageResponse:
        return self.delegate_for("methodology").fetch_methodology(request)

    def fetch_historical_reports(self, request: StageRequest) -> StageResponse:
        return self.delegate_for("historical_reports").fetch_historical_reports(request)

    def fetch_historical_recommendations(self, request: StageRequest) -> StageResponse:
        return self.delegate_for("historical_recommendations").fetch_historical_recommendations(
            request
        )

    def build_briefing(self, request: StageRequest) -> StageResponse:
        return self.delegate_for("briefing").build_briefing(request)

    # -- plumbing ----------------------------------------------------------

    def health(self) -> HealthReport:
        if not self.live_stages:
            return self.example.health()
        report = self.live.health()
        if self.is_uniform:
            return report
        served = len(self.live_stages)
        suffix = f" · {served}/{len(STAGE_KEYS)} stages live, the rest on example data"
        return HealthReport(
            ok=report.ok,
            detail=report.detail + suffix,
            latency_ms=report.latency_ms,
            version=report.version,
        )

    def close(self) -> None:
        self.live.close()
        self.example.close()


def resolve_live_stages(settings: Settings) -> frozenset[str]:
    """Which stages should call the real backend.

    ``AUDIT_LIVE_STAGES`` wins when set; otherwise ``AUDIT_BACKEND_MODE``
    decides for every stage at once. A stage named there but not recognised is
    ignored rather than fatal — a typo should not take the app down.
    """
    named = settings.live_stages
    if named is None:
        return frozenset() if settings.is_mock else frozenset(STAGE_KEYS)
    if not settings.base_url:
        # Nothing to call. Fall back rather than fail every named stage.
        return frozenset()
    return frozenset(key for key in named if key in STAGE_KEYS)


def build_backend(settings: Settings) -> BackendAPI:
    """The backend the app talks to, assembled from configuration."""
    live_stages = resolve_live_stages(settings)
    example = ExampleDataAPI(settings)
    if not live_stages:
        return example
    live = HttpBackendAPI(settings)
    if live_stages == frozenset(STAGE_KEYS):
        return live
    return StageRouter(live, example, live_stages, settings)
