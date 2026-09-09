"""The mission-preparation pipeline: the stages, in order.

This module is the single source of truth for what the pipeline *is*: stage
order, dependencies, which model parses each payload, which backend method
serves it, and which stage name is sent to the backend. The UI, the client, the
router and the exporter all read from here — nothing counts stages for itself —
so inserting a stage is an entry in ``STAGES`` plus its model, its
``BackendAPI`` method and a renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .models import (
    Briefing,
    HistoricalRecommendations,
    HistoricalReports,
    Methodology,
    MissionMetadata,
    RiskEvents,
    ScopeUnderstanding,
)

if TYPE_CHECKING:
    from .models import LooseModel


@dataclass(frozen=True)
class StageSpec:
    """Static description of one pipeline stage."""

    key: str
    """Front-end identifier and the ``{stage}`` value sent to the backend."""

    order: int
    label: str
    short_label: str
    icon: str
    model: type[LooseModel]
    depends_on: tuple[str, ...]
    purpose: str
    """One sentence shown above the stage, so a new joiner knows why it runs."""

    hitl_note: str
    """What the analyst is actually being asked to check at this checkpoint."""

    api_method: str
    """Name of the :class:`~audit_front.api.BackendAPI` method that serves this stage.

    Declared here rather than in a separate lookup table so the stage list stays
    the only place the pipeline is defined; `BackendAPI.run_stage` dispatches on
    it, and a test asserts every name resolves to a real method.
    """

    critical_checkpoint: bool = False
    """True for stages where an unreviewed error contaminates everything after."""

    @property
    def number(self) -> int:
        return self.order + 1

    @property
    def title(self) -> str:
        return f"{self.number}. {self.label}"


STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        key="mission_metadata",
        api_method="fetch_mission_metadata",
        order=0,
        label="Mission metadata",
        short_label="Metadata",
        icon="📋",
        model=MissionMetadata,
        depends_on=(),
        purpose=(
            "Pull the mission's identity from the audit tooling: name, brief scope, legal "
            "entities, risk families, activities and business lines."
        ),
        hitl_note=(
            "Check the entity list and risk families against what you know of the mission. "
            "Reference data is often stale — an entity missing here is missing everywhere after."
        ),
    ),
    StageSpec(
        key="scope_understanding",
        api_method="analyse_mission_scope",
        order=1,
        label="Mission scope understanding",
        short_label="Scope",
        icon="🎯",
        model=ScopeUnderstanding,
        depends_on=("mission_metadata",),
        purpose=(
            "Decide which dimension actually defines the perimeter (entity, country, risk or "
            "process) and produce the filter set used by every later stage."
        ),
        hitl_note=(
            "This filter drives every stage after it. Too broad and you drown in irrelevant data; "
            "too narrow and you miss losses and recommendations that belong in scope."
        ),
        critical_checkpoint=True,
    ),
    StageSpec(
        key="risk_events",
        api_method="fetch_risk_events",
        order=2,
        label="Operational risk events in scope",
        short_label="Risk events",
        icon="⚠️",
        model=RiskEvents,
        depends_on=("scope_understanding",),
        purpose=(
            "Retrieve operational-loss events recorded against the validated perimeter and "
            "read what they imply for fieldwork."
        ),
        hitl_note=(
            "An empty result is a finding in itself, not a failure: it means no structured "
            "loss data surfaced. Exclude events you judge out of scope, and say why."
        ),
    ),
    StageSpec(
        key="methodology",
        api_method="fetch_methodology",
        order=3,
        label="Methodology references",
        short_label="Methodology",
        icon="📐",
        model=Methodology,
        depends_on=("scope_understanding",),
        purpose=(
            "Look for a registered audit methodology ('methodo') matching this scope, and "
            "fall back to the standard approach when none exists."
        ),
        hitl_note=(
            "If the search returned nothing, add any methodology note you already hold "
            "locally — the register is not exhaustive."
        ),
    ),
    StageSpec(
        key="historical_reports",
        api_method="fetch_historical_reports",
        order=4,
        label="Historical 3LOD reports",
        short_label="3LOD reports",
        icon="📚",
        model=HistoricalReports,
        depends_on=("scope_understanding",),
        purpose=(
            "Find reports issued on this perimeter by the three lines of defence in earlier "
            "assignments, and summarise their key messages and the IGAD positions taken."
        ),
        hitl_note=(
            "Reports carry positions the mission will be read against. Anything the search "
            "missed — a 2LOD review filed locally, a regulator letter, a report on a sister "
            "entity — belongs here, and a report you judge irrelevant should be excluded and "
            "the reason recorded."
        ),
    ),
    StageSpec(
        key="historical_recommendations",
        api_method="fetch_historical_recommendations",
        order=5,
        label="Historical recommendations",
        short_label="History",
        icon="🗂️",
        model=HistoricalRecommendations,
        depends_on=("scope_understanding",),
        purpose=(
            "Surface recommendations issued on this perimeter in earlier cycles, so the "
            "mission starts from the open backlog rather than from zero."
        ),
        hitl_note=(
            "The search keys on this mission ID. Prior entity-level or topic-level missions "
            "(an AML-only or HR-only review) may hold recommendations it cannot see — add them."
        ),
    ),
    StageSpec(
        key="briefing",
        api_method="build_briefing",
        order=6,
        label="Consolidated pre-mission briefing",
        short_label="Briefing",
        icon="📄",
        model=Briefing,
        depends_on=(
            "mission_metadata",
            "scope_understanding",
            "risk_events",
            "methodology",
            "historical_reports",
            "historical_recommendations",
        ),
        purpose=(
            "Synthesise every validated stage into the briefing the audit team walks in "
            "with: objective, perimeter, thematic axes, risk landscape and open questions."
        ),
        hitl_note=(
            "This is the deliverable. Edit it as your own document — the export carries "
            "your version, with the AI's original kept in the audit trail."
        ),
    ),
)

STAGE_BY_KEY: dict[str, StageSpec] = {stage.key: stage for stage in STAGES}
STAGE_KEYS: tuple[str, ...] = tuple(stage.key for stage in STAGES)


def get_stage(key: str) -> StageSpec:
    try:
        return STAGE_BY_KEY[key]
    except KeyError:  # pragma: no cover - guarded by STAGE_KEYS everywhere
        raise KeyError(f"Unknown pipeline stage {key!r}") from None


def next_stage(key: str) -> StageSpec | None:
    """The stage that follows ``key``, or None at the end of the pipeline."""
    stage = get_stage(key)
    if stage.order + 1 >= len(STAGES):
        return None
    return STAGES[stage.order + 1]


def downstream_of(key: str) -> tuple[StageSpec, ...]:
    """Stages that depend on ``key``, directly or transitively.

    Used to invalidate later results when an analyst edits an earlier stage:
    a scope change makes the risk-event pull stale, and the UI must say so
    rather than leave a briefing built on a perimeter that no longer holds.
    """
    dirty = {key}
    affected: list[StageSpec] = []
    for stage in STAGES[get_stage(key).order + 1 :]:
        if dirty.intersection(stage.depends_on):
            dirty.add(stage.key)
            affected.append(stage)
    return tuple(affected)
