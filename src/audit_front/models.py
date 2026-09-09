"""Typed views over the backend payloads.

The backend is owned by another team and its exact JSON shape may drift, so
every model here is deliberately *tolerant*:

* all fields are optional -- a missing block renders as "not provided", never
  as a crash;
* unknown fields are kept (``extra="allow"``) and stay visible in the raw
  payload view;
* incoming keys are normalised, so ``MissionName``, ``missionName`` and
  ``mission_name`` all land on the same field. The sample outputs mix
  PascalCase (``PrimaryScopeDriver``) with prose keys ("Entities in scope"),
  which is exactly what this normalisation absorbs.

Rendering never depends on a field being present; it depends on the model
parsing at all, which the tolerance above guarantees.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, get_args, get_origin

from pydantic import BaseModel, ConfigDict, model_validator

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Mojibake seen in the sample outputs: UTF-8 punctuation decoded as cp1252.
# The backend emits these; repairing them here keeps the UI clean without
# asking the backend team to change anything.
_MOJIBAKE = {
    "â€“": "–",  # en dash
    "â€”": "—",  # em dash
    "â€™": "’",  # right single quote
    "â€œ": "“",  # left double quote
    "â€": "”",  # right double quote
    "â€˜": "‘",  # left single quote
    "â†’": "→",  # right arrow
    "â€¢": "•",  # bullet
}


def fix_mojibake(text: str) -> str:
    """Repair cp1252-decoded UTF-8 punctuation in backend strings."""
    for bad, good in _MOJIBAKE.items():
        if bad in text:
            text = text.replace(bad, good)
    return text


def _norm_key(key: str) -> str:
    """``"Entities in scope"`` -> ``"entitiesinscope"``; ``"RiskL1"`` -> ``"riskl1"``."""
    return _NON_ALNUM.sub("", str(key).lower())


def as_list(value: Any) -> list[Any]:
    """Coerce scalar / None / list into a list, dropping empties."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [v for v in value if v not in (None, "")]
    if isinstance(value, dict):
        # `{}` is how the sample output spells "empty result set".
        return [value] if value else []
    return [value] if value != "" else []


def as_str_list(value: Any) -> list[str]:
    """Coerce to a list of trimmed strings, splitting newline-separated text."""
    if isinstance(value, str):
        parts = [p.strip(" \t-•") for p in fix_mojibake(value).splitlines()]
        return [p for p in parts if p]
    out: list[str] = []
    for item in as_list(value):
        text = fix_mojibake(str(item)).strip()
        if text:
            out.append(text)
    return out


class LooseModel(BaseModel):
    """Base model with key normalisation and unknown-field retention."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)

    # Normalised incoming key -> field name, for backend spellings that do not
    # normalise onto the field name by themselves.
    key_aliases: ClassVar[dict[str, str]] = {}

    @classmethod
    def _list_coercers(cls) -> dict[str, Any]:
        """Field name -> coercion, for every field declared as a list.

        Derived from the annotations rather than hand-written per model, so a
        new list field is tolerant the moment it is declared.
        """
        cached = cls.__dict__.get("_af_list_coercers")
        if cached is None:
            cached = {}
            for name, field_info in cls.model_fields.items():
                if get_origin(field_info.annotation) is list:
                    args = get_args(field_info.annotation)
                    cached[name] = as_str_list if args and args[0] is str else as_list
            cls._af_list_coercers = cached  # type: ignore[attr-defined]
        return cached

    @model_validator(mode="before")
    @classmethod
    def _normalise_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        by_norm = {_norm_key(name): name for name in cls.model_fields}
        by_norm.update(cls.key_aliases)
        out: dict[str, Any] = {}
        for raw_key, value in data.items():
            target = by_norm.get(_norm_key(raw_key), raw_key)
            # First spelling wins; stops an alias from clobbering an exact match.
            out.setdefault(target, value)

        # Coerce *after* mapping, not before. A scalar arriving under an alias
        # (`{"country": "UNITED KINGDOM"}`, `{"analysis": "one\ntwo"}`) is only
        # recognisable as a list field once the key has been resolved — doing
        # this first made such payloads fail validation, which `parsed()` then
        # swallowed into an empty model and rendered as a blank section.
        for name, coerce in cls._list_coercers().items():
            if name in out:
                out[name] = coerce(out[name])
        return out

    def extras(self) -> dict[str, Any]:
        """Backend fields this front-end does not model explicitly."""
        return dict(self.__pydantic_extra__ or {})


# ---------------------------------------------------------------------------
# Stage 1 -- mission metadata
# ---------------------------------------------------------------------------


class ActivityNode(LooseModel):
    """One node of the ActivityThree process tree (e.g. ``A22.01.01 - AML``)."""

    code: str | None = None
    label: str | None = None
    children: list[ActivityNode] = []

    key_aliases: ClassVar[dict[str, str]] = {
        "name": "label",
        "title": "label",
        "activity": "label",
        "id": "code",
        "sub": "children",
        "subactivities": "children",
        "nodes": "children",
    }

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data: Any) -> Any:
        """Accept ``"A22.01 - Financial Crime"`` as readily as a dict."""
        if isinstance(data, str):
            text = fix_mojibake(data).strip()
            code, sep, label = _split_once(text)
            return {"code": code, "label": label} if sep else {"label": text}
        return data

    @property
    def display(self) -> str:
        if self.code and self.label:
            return f"{self.code} — {self.label}"
        return self.label or self.code or ""

    def flatten(self, depth: int = 0) -> list[tuple[int, ActivityNode]]:
        """Depth-annotated pre-order walk, for table / indented rendering."""
        rows: list[tuple[int, ActivityNode]] = [(depth, self)]
        for child in self.children:
            rows.extend(child.flatten(depth + 1))
        return rows


def _split_once(text: str) -> tuple[str, str, str]:
    """Split ``"A22 - Compliance"`` into (code, separator, label)."""
    match = re.match(r"^([A-Za-z0-9./_ ]{1,24}?)\s*([-–—:])\s*(.+)$", text)
    if match:
        return match.group(1).strip(), match.group(2), match.group(3).strip()
    return text, "", ""


class MissionMetadata(LooseModel):
    """Stage 1 -- identity of the mission, as held in the audit tooling."""

    mission_id: str | None = None
    mission_name: str | None = None
    brief_scope: str | None = None
    main_business_line: str | None = None
    countries: list[str] = []
    entities: list[str] = []
    risk_families: list[str] = []
    activities: list[ActivityNode] = []
    business_lines: list[str] = []
    audit_cycle: str | None = None
    planned_start: str | None = None
    planned_end: str | None = None

    key_aliases: ClassVar[dict[str, str]] = {
        "id": "mission_id",
        "code": "mission_id",
        "missioncode": "mission_id",
        "name": "mission_name",
        "scope": "brief_scope",
        "briefscopetext": "brief_scope",
        "mainbusinessline": "main_business_line",
        "mainbusinesslineprimary": "main_business_line",
        "primarybusinessline": "main_business_line",
        "country": "countries",
        "entitiesinscope": "entities",
        "entitylist": "entities",
        "keyriskfamilies": "risk_families",
        "keyriskfamiliesriskl1": "risk_families",
        "riskl1": "risk_families",
        "risks": "risk_families",
        "mainactivities": "activities",
        "mainactivitiesprocesses": "activities",
        "activitythree": "activities",
        "processes": "activities",
        "businesslinesinvolved": "business_lines",
    }

# ---------------------------------------------------------------------------
# Stage 2 -- mission scope understanding
# ---------------------------------------------------------------------------


class ScopeUnderstanding(LooseModel):
    """Stage 2 -- the filter set every later stage is executed against.

    This is the highest-value human-in-the-loop checkpoint: an over-broad or
    under-broad entity filter silently distorts every stage after it.
    """

    mission_name: str | None = None
    brief_scope: str | None = None
    primary_scope_driver: str | None = None  # e.g. "Entity-driven"
    scope_coverage: str | None = None  # e.g. "Exact" / "Approximate"
    missing_dimensions: list[str] = []
    entity_filter: list[str] = []
    country_filter: list[str] = []
    risk_filter: list[str] = []
    activity_filter: list[str] = []
    business_line_filter: list[str] = []
    reasoning: list[str] = []

    key_aliases: ClassVar[dict[str, str]] = {
        "name": "mission_name",
        "scope": "brief_scope",
        "scopedriver": "primary_scope_driver",
        "driver": "primary_scope_driver",
        "coverage": "scope_coverage",
        "missingdimension": "missing_dimensions",
        "entities": "entity_filter",
        "entityfilters": "entity_filter",
        "countries": "country_filter",
        "risks": "risk_filter",
        "riskfilters": "risk_filter",
        "activities": "activity_filter",
        "businesslines": "business_line_filter",
        "reasoningsummary": "reasoning",
        "rationale": "reasoning",
        "justification": "reasoning",
    }

    LIST_FIELDS: ClassVar[tuple[str, ...]] = (
        "missing_dimensions",
        "entity_filter",
        "country_filter",
        "risk_filter",
        "activity_filter",
        "business_line_filter",
        "reasoning",
    )

    @property
    def is_empty(self) -> bool:
        """True when no dimension constrains the perimeter -- worth warning about."""
        return not any(
            [
                self.entity_filter,
                self.country_filter,
                self.risk_filter,
                self.activity_filter,
                self.business_line_filter,
            ]
        )


# ---------------------------------------------------------------------------
# Stage 3 -- operational risk events in scope
# ---------------------------------------------------------------------------


class LossEvent(LooseModel):
    """One operational-loss record returned for the perimeter."""

    event_id: str | None = None
    title: str | None = None
    entity: str | None = None
    event_date: str | None = None
    risk_category: str | None = None
    gross_amount: float | None = None
    net_amount: float | None = None
    currency: str | None = None
    status: str | None = None
    description: str | None = None

    key_aliases: ClassVar[dict[str, str]] = {
        "id": "event_id",
        "eventid": "event_id",
        "reference": "event_id",
        "ref": "event_id",
        "label": "title",
        "name": "title",
        "legalentity": "entity",
        "date": "event_date",
        "occurrencedate": "event_date",
        "riskl1": "risk_category",
        "category": "risk_category",
        "grossloss": "gross_amount",
        "amount": "gross_amount",
        "netloss": "net_amount",
        "ccy": "currency",
    }


class RiskEvents(LooseModel):
    """Stage 3 -- operational-loss picture for the perimeter.

    An empty ``events`` list is a meaningful result, not a failure: it means
    no structured loss data surfaced, which pushes fieldwork towards
    qualitative sources. The UI says so explicitly rather than showing a void.
    """

    events: list[LossEvent] = []
    total_count: int | None = None
    total_amount: float | None = None
    currency: str | None = None
    period: str | None = None
    interpretation: list[str] = []

    key_aliases: ClassVar[dict[str, str]] = {
        "losses": "events",
        "operationallosses": "events",
        "lossevents": "events",
        "items": "events",
        "results": "events",
        "count": "total_count",
        "interpretationforthemission": "interpretation",
        "analysis": "interpretation",
        "comment": "interpretation",
    }

    @property
    def resolved_count(self) -> int:
        return self.total_count if self.total_count is not None else len(self.events)


# ---------------------------------------------------------------------------
# Stage 4 -- methodology references
# ---------------------------------------------------------------------------


class MethodologyRef(LooseModel):
    ref_id: str | None = None
    title: str | None = None
    version: str | None = None
    url: str | None = None
    summary: str | None = None
    scope_match: str | None = None

    key_aliases: ClassVar[dict[str, str]] = {
        "id": "ref_id",
        "reference": "ref_id",
        "name": "title",
        "label": "title",
        "link": "url",
        "description": "summary",
        "match": "scope_match",
        "relevance": "scope_match",
    }


class Methodology(LooseModel):
    """Stage 4 -- registered audit methodology ("methodo") for this scope."""

    found: bool | None = None
    references: list[MethodologyRef] = []
    implications: list[str] = []
    recommended_approach: list[str] = []
    message: str | None = None

    key_aliases: ClassVar[dict[str, str]] = {
        "methodo": "references",
        "methodos": "references",
        "methodologies": "references",
        "items": "references",
        "results": "references",
        "approach": "recommended_approach",
        "standardapproach": "recommended_approach",
        "result": "message",
        "methodologyresult": "message",
    }

    @property
    def resolved_found(self) -> bool:
        return bool(self.references) if self.found is None else bool(self.found)


# ---------------------------------------------------------------------------
# Stage 5 -- historical 3LOD reports
# ---------------------------------------------------------------------------


class ThreeLodReport(LooseModel):
    """One report issued on this perimeter by any line of defence.

    Covers 1LOD self-assessments, 2LOD reviews, 3LOD (IGAD) audit reports and
    external/regulatory reports, because the mission will be read against all
    of them — not only against internal audit's own back catalogue.
    """

    report_id: str | None = None
    title: str | None = None
    line_of_defence: str | None = None  # "1LOD" | "2LOD" | "3LOD" | "External"
    issuer: str | None = None  # e.g. "IGAD", "Compliance UK", "FCA"
    mission_ref: str | None = None  # the assignment that produced it
    entity: str | None = None
    published_date: str | None = None
    period_covered: str | None = None
    rating: str | None = None  # audit opinion / conclusion
    scope_match: str | None = None  # why it is relevant here
    key_messages: list[str] = []
    igad_position: str | None = None  # the position IGAD took in this report
    status: str | None = None  # "Final" | "Draft" | "Superseded"
    url: str | None = None
    source: str | None = None  # "backend" | "analyst" -- stamped by the front-end

    key_aliases: ClassVar[dict[str, str]] = {
        "id": "report_id",
        "reference": "report_id",
        "ref": "report_id",
        "reportreference": "report_id",
        "name": "title",
        "label": "title",
        "lod": "line_of_defence",
        "line": "line_of_defence",
        "lineofdefense": "line_of_defence",
        "defenceline": "line_of_defence",
        "author": "issuer",
        "issuedby": "issuer",
        "function": "issuer",
        "mission": "mission_ref",
        "missionid": "mission_ref",
        "assignment": "mission_ref",
        "legalentity": "entity",
        "date": "published_date",
        "issuedate": "published_date",
        "publicationdate": "published_date",
        "period": "period_covered",
        "opinion": "rating",
        "conclusion": "rating",
        "relevance": "scope_match",
        "match": "scope_match",
        "messages": "key_messages",
        "keymessage": "key_messages",
        "findings": "key_messages",
        "summary": "key_messages",
        "igadposition": "igad_position",
        "position": "igad_position",
        "link": "url",
    }

    @property
    def is_third_line(self) -> bool:
        lod = (self.line_of_defence or "").lower().replace(" ", "")
        return "3lod" in lod or "3rd" in lod or "thirdline" in lod


class HistoricalReports(LooseModel):
    """Stage 5 -- prior 3LOD reporting on the perimeter, and what it said.

    The point is not the list but the positions: a mission that contradicts a
    position IGAD took eighteen months ago needs to know that before fieldwork,
    not at the clearance meeting.
    """

    found: bool | None = None
    reports: list[ThreeLodReport] = []
    key_messages: list[str] = []  # synthesis across the reports
    igad_positions: list[str] = []  # the positions IGAD has taken
    implications: list[str] = []
    message: str | None = None

    key_aliases: ClassVar[dict[str, str]] = {
        "items": "reports",
        "results": "reports",
        "documents": "reports",
        "historicalreports": "reports",
        "previousreports": "reports",
        "lodreports": "reports",
        "threelodreports": "reports",
        "messages": "key_messages",
        "summary": "key_messages",
        "keymessagesummary": "key_messages",
        "positions": "igad_positions",
        "igadposition": "igad_positions",
        "auditpositions": "igad_positions",
        "reportsresult": "message",
        "result": "message",
    }

    LIST_FIELDS: ClassVar[tuple[str, ...]] = (
        "key_messages",
        "igad_positions",
        "implications",
    )

    @property
    def resolved_found(self) -> bool:
        return bool(self.reports) if self.found is None else bool(self.found)

    @property
    def third_line_reports(self) -> list[ThreeLodReport]:
        return [report for report in self.reports if report.is_third_line]

    @property
    def lines_covered(self) -> list[str]:
        """Distinct lines of defence represented, in a stable order."""
        seen: list[str] = []
        for report in self.reports:
            line = (report.line_of_defence or "Unspecified").strip()
            if line not in seen:
                seen.append(line)
        return seen

    def resolved_positions(self) -> list[str]:
        """Stage-level IGAD positions, falling back to the per-report ones."""
        if self.igad_positions:
            return list(self.igad_positions)
        return [
            f"{report.report_id or report.title or 'Report'}: {report.igad_position}"
            for report in self.reports
            if report.igad_position
        ]


# ---------------------------------------------------------------------------
# Stage 6 -- historical recommendations
# ---------------------------------------------------------------------------


class Recommendation(LooseModel):
    rec_id: str | None = None
    title: str | None = None
    mission_ref: str | None = None
    entity: str | None = None
    risk_family: str | None = None
    criticality: str | None = None
    status: str | None = None
    due_date: str | None = None
    description: str | None = None
    source: str | None = None  # "backend" | "analyst" -- stamped by the front-end

    key_aliases: ClassVar[dict[str, str]] = {
        "id": "rec_id",
        "reference": "rec_id",
        "recommendationid": "rec_id",
        "name": "title",
        "label": "title",
        "mission": "mission_ref",
        "missionid": "mission_ref",
        "legalentity": "entity",
        "riskl1": "risk_family",
        "risk": "risk_family",
        "severity": "criticality",
        "priority": "criticality",
        "state": "status",
        "duedate": "due_date",
        "deadline": "due_date",
    }


class HistoricalRecommendations(LooseModel):
    """Stage 6 -- open/closed recommendations touching the perimeter."""

    found: bool | None = None
    recommendations: list[Recommendation] = []
    implications: list[str] = []
    message: str | None = None

    key_aliases: ClassVar[dict[str, str]] = {
        "items": "recommendations",
        "results": "recommendations",
        "historicalrecommendations": "recommendations",
        "previousrecommendations": "recommendations",
        "recommendationsresult": "message",
        "result": "message",
    }

    @property
    def resolved_found(self) -> bool:
        return bool(self.recommendations) if self.found is None else bool(self.found)

    @property
    def open_items(self) -> list[Recommendation]:
        closed = {"closed", "done", "implemented", "cancelled"}
        return [r for r in self.recommendations if (r.status or "").lower() not in closed]


# ---------------------------------------------------------------------------
# Stage 7 -- consolidated pre-mission briefing
# ---------------------------------------------------------------------------


class ThematicAxis(LooseModel):
    title: str | None = None
    points: list[str] = []

    key_aliases: ClassVar[dict[str, str]] = {
        "name": "title",
        "axis": "title",
        "label": "title",
        "bullets": "points",
        "details": "points",
        "content": "points",
    }

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data: Any) -> Any:
        """A bare string is the axis title; lists are coerced by the base class."""
        if isinstance(data, str):
            return {"title": fix_mojibake(data)}
        return data


class Briefing(LooseModel):
    """Stage 7 -- the deliverable the audit team actually walks in with."""

    objective: str | None = None
    perimeter: list[str] = []
    thematic_axes: list[ThematicAxis] = []
    risk_landscape: list[str] = []
    methodology_stance: list[str] = []
    historical_context: list[str] = []
    open_questions: list[str] = []
    markdown: str | None = None  # backend-rendered version, if any

    key_aliases: ClassVar[dict[str, str]] = {
        "missionobjective": "objective",
        "missionobjectiveoperationalview": "objective",
        "goal": "objective",
        "perimetertouse": "perimeter",
        "perimetertouseforallpremissionwork": "perimeter",
        "entities": "perimeter",
        "keythematicaxes": "thematic_axes",
        "keythematicaxestopreparefor": "thematic_axes",
        "axes": "thematic_axes",
        "themes": "thematic_axes",
        "risklandscape": "risk_landscape",
        "risklandscapeforpreparation": "risk_landscape",
        "methodologystance": "methodology_stance",
        "historicalcontext": "historical_context",
        "questions": "open_questions",
        "openpoints": "open_questions",
        "text": "markdown",
        "content": "markdown",
    }

    LIST_FIELDS: ClassVar[tuple[str, ...]] = (
        "perimeter",
        "risk_landscape",
        "methodology_stance",
        "historical_context",
        "open_questions",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_markdown(cls, data: Any) -> Any:
        """A bare string is a rendered briefing; lists are coerced by the base class."""
        if isinstance(data, str):
            return {"markdown": fix_mojibake(data)}
        return data
