"""Offline backend with bundled sample missions.

The real backend cannot be shared, so mock mode exists to keep the front-end
developable and demonstrable on its own. It is not decoration: it honours the
``context`` argument, so a scope edited by the analyst genuinely changes the
loss events, the recommendations and the final briefing. That is the whole
human-in-the-loop claim, exercised without a network.

``26-IRB/AYVENS-019`` reproduces the sample output that shaped this UI —
including its three empty result sets, which the interface has to present as
findings rather than as blanks. ``26-IRB/AYVENS-021`` is the opposite case:
losses, a registered methodology and an open recommendation backlog.
"""

from __future__ import annotations

import random
import time
from typing import Any

from .client import BackendError, HealthReport, StageResponse
from .config import Settings
from .pipeline import StageSpec

AYVENS_UK = "26-IRB/AYVENS-019"
AYVENS_DE = "26-IRB/AYVENS-021"

_UK_ENTITIES = [
    "ALD AUTOMOTIVE LIMITED",
    "AUTOMOTIVE LEASING LIMITED",
    "DIAL CONTRACTS LIMITED",
    "DIAL VEHICLE MANAGEMENT SERVICES LTD",
    "FORD FLEET MANAGEMENT UK LIMITED",
    "INTERNAL FLEET PURCHASING LIMITED",
    "LEASEPLAN UK LIMITED",
    "NETWORK VEHICLES LTD",
]

_UK_RISK_FAMILIES = [
    "Anti-Bribery & Corruption",
    "Anti-Money Laundering / CTF",
    "Business & Strategy risks",
    "Competition law",
    "Data protection",
    "Employment law & employer obligations",
    "Errors in operating processes",
    "Ethics & Conduct",
    "Know Your Customer",
    "Risks related to operating leasing activities",
    "Staff and skills inadequacy",
    "Sustainability risks",
]

_UK_ACTIVITIES: list[dict[str, Any]] = [
    {"code": "A01", "label": "Clients & Third parties"},
    {
        "code": "A03.03.03",
        "label": "Rentals with/without Purchase Option; Short & Long Term Rentals",
    },
    {"code": "A18.04 / A18.04.01", "label": "Entity Management"},
    {
        "code": "A22",
        "label": "Compliance",
        "children": [
            {
                "code": "A22.01",
                "label": "Financial Crime",
                "children": [
                    {"code": "A22.01.01", "label": "AML"},
                    {"code": "A22.01.02", "label": "Embargoes & Sanctions"},
                    {"code": "A22.01.03", "label": "KYC"},
                ],
            },
            {
                "code": "A22.02",
                "label": "Other Regulatory Compliance Activities",
                "children": [
                    {"code": "A22.02.02", "label": "Client & Investor Protection"},
                    {"code": "A22.02.04", "label": "Compliance Data Protection"},
                    {"code": "A22.02.05", "label": "Ethics, Conduct & Anti-Corruption"},
                ],
            },
        ],
    },
    {
        "code": "A26",
        "label": "Human Resources",
        "children": [
            {
                "code": "A26.01",
                "label": "HR Management",
                "children": [
                    {"code": "A26.01.01", "label": "Compensation & Benefits"},
                    {"code": "A26.01.02", "label": "Careers Management"},
                    {"code": "A26.01.03", "label": "Administrative & Payroll"},
                    {"code": "A26.01.04", "label": "Employment & Skills Management"},
                    {"code": "A26.01.05", "label": "Social Relations Management"},
                ],
            }
        ],
    },
]

_UK_BUSINESS_LINES = [
    "AVNS/IBFS/ALDI/UK/IBFS/ALDA/UK/FFM",
    "AVNS/IBFS/ALDI/UK/IBFS/ALDA/UK/FIN",
    "AVNS/IBFS/ALDI/UK/IBFS/ALDA/UK/HR",
    "AVNS/IBFS/ALDI/UK/IBFS/ALDA/UK/LEGCPL",
    "AVNS/IBFS/ALDI/UK/IBFS/ALDA/UK/MSQUAL",
    "AVNS/IBFS/ALDI/UK/IBFS/ALDA/UK/RISKCPL",
    "AVNS/IBFS/ALDI/UK/IBFS/ALDA/UK/SALMKT",
    "AVNS/UK/IBFS/ALDA/LPUK/GBR/CPLE",
    "AVNS/UK/IBFS/ALDA/LPUK/GBR/FIN",
    "AVNS/UK/IBFS/ALDA/LPUK/GBR/HR",
]

_DE_ENTITIES = [
    "ALD AUTOMOTIVE GMBH",
    "LEASEPLAN DEUTSCHLAND GMBH",
    "AYVENS REMARKETING GMBH",
]


# ---------------------------------------------------------------------------
# Sample mission definitions
# ---------------------------------------------------------------------------

_MISSIONS: dict[str, dict[str, Any]] = {
    AYVENS_UK: {
        "mission_metadata": {
            "mission_id": AYVENS_UK,
            "mission_name": (
                "2026_Ayvens United Kingdom - Asset Risk, Human Resources, Compliance, "
                "and Culture & Conduct"
            ),
            "brief_scope": (
                "Part of a multi-year plan to review topics due as per the audit cycle "
                "(periodic/thematic review rather than ad-hoc)."
            ),
            "main_business_line": "AVNS/UK/IBFS/ALDA/LPUK/GBR/FIN",
            "countries": ["UNITED KINGDOM"],
            "entities": _UK_ENTITIES,
            "risk_families": _UK_RISK_FAMILIES,
            "activities": _UK_ACTIVITIES,
            "business_lines": _UK_BUSINESS_LINES,
            "audit_cycle": "2026 — periodic",
        },
        "scope_understanding": {
            "mission_name": (
                "2026_Ayvens United Kingdom - Asset Risk, Human Resources, Compliance, "
                "and Culture & Conduct"
            ),
            "brief_scope": (
                "Multi-year audit cycle review of several thematic areas (asset risk, HR, "
                "compliance, culture & conduct) across Ayvens UK entities."
            ),
            "primary_scope_driver": "Entity-driven",
            "scope_coverage": "Exact",
            "missing_dimensions": [],
            "entity_filter": _UK_ENTITIES,
            "reasoning": [
                "The entity list is more precise than the country axis and already embeds "
                "the UK dimension.",
                "The mission title covers multiple themes (asset risk, HR, compliance, "
                "culture & conduct) as part of the audit cycle; no single risk or regulation "
                "uniquely defines the scope.",
                "Country is redundant because all entities are UK-based and explicitly listed.",
                "Regulations and risk types (AML, KYC, Data Protection, Ethics) are thematic "
                "components, not the primary scoping driver.",
                "Therefore the minimal and accurate filter set for all subsequent analyses is "
                "the closed list of Ayvens UK entities.",
            ],
        },
        "risk_events": {
            "events": [],
            "total_count": 0,
            "period": "2023-01-01 to 2026-08-31",
            "interpretation": [
                "No recorded operational loss events were retrieved for the specified entities "
                "within the parameters used by the pre-mission tool.",
                "This does not prove absence of incidents; it only indicates that no structured "
                "loss data has been surfaced for the perimeter.",
                "Rely more heavily on qualitative sources (risk maps, RCSA, incident logs, "
                "complaints, HR cases, compliance alerts) during fieldwork.",
                "Pay attention to emerging or non-quantified risks in asset risk, HR, compliance "
                "and culture & conduct, as they may not yet be reflected in loss databases.",
            ],
        },
        "methodology": {
            "found": False,
            "references": [],
            "message": "No Methodo found for this mission",
            "implications": [
                "There is no pre-registered, mission-specific methodological template or prior "
                "structured 'methodo' for this exact scope.",
            ],
            "recommended_approach": [
                "Apply the standard internal audit methodology: risk-based scoping, process "
                "walkthroughs, control testing, sampling, thematic reviews.",
                "Tailor it to asset risk in operating leasing activities.",
                "Tailor it to HR processes (compensation, careers, payroll, skills, social "
                "relations).",
                "Tailor it to compliance (AML/CTF, KYC, sanctions, data protection, client "
                "protection, ethics & anti-corruption).",
                "Tailor it to culture & conduct (tone from the top, staff behaviour, incentives, "
                "whistleblowing, disciplinary processes).",
            ],
        },
        "historical_recommendations": {
            "found": False,
            "recommendations": [],
            "message": "No previous recommendation on the scope",
            "implications": [
                "The mission is not constrained by a backlog of prior recommendations specific "
                "to this combined scope (asset risk + HR + compliance + culture & conduct).",
                "Check locally whether there are entity-level or topic-specific recommendations "
                "that may not have been captured under this exact mission ID (e.g. prior "
                "AML-only or HR-only missions).",
                "Treat this mission as an opportunity to establish a baseline of findings and "
                "recommendations for future cycles.",
            ],
        },
        "briefing": {
            "objective": (
                "Perform a multi-thematic, entity-driven review across Ayvens UK legal entities, "
                "focusing on asset risk, human resources, compliance (including financial crime, "
                "data protection, client protection), and culture & conduct, as part of the "
                "scheduled audit cycle."
            ),
            "thematic_axes": [
                {
                    "title": "Asset Risk / Operating Leasing Activities",
                    "points": [
                        "Risk related to operating leasing activities (residual value, credit "
                        "risk interaction, asset management, repossession, remarketing).",
                        "Errors in operating processes (contract setup, billing, collections, "
                        "asset lifecycle).",
                    ],
                },
                {
                    "title": "Human Resources",
                    "points": [
                        "Employment law and employer obligations (contracts, working time, "
                        "disciplinary procedures, equality, diversity & inclusion).",
                        "HR management: compensation & benefits, careers, payroll, skills "
                        "management, social relations (unions, employee representatives).",
                        "Staff and skills adequacy (capacity, competence, training, succession "
                        "planning).",
                    ],
                },
                {
                    "title": "Compliance & Financial Crime",
                    "points": [
                        "AML/CTF, KYC, sanctions/embargoes (A22.01.x).",
                        "Other regulatory compliance: client & investor protection, data "
                        "protection (GDPR), ethics & anti-corruption.",
                        "Governance of the compliance function within the Ayvens UK perimeter.",
                    ],
                },
                {
                    "title": "Culture & Conduct",
                    "points": [
                        "Ethics & conduct risk, anti-bribery & corruption.",
                        "Incentive structures, performance management, and their alignment with "
                        "risk appetite.",
                        "Speak-up mechanisms, disciplinary actions, and management response to "
                        "misconduct.",
                    ],
                },
            ],
            "risk_landscape": [
                "Multiple risk families are relevant: financial crime, data protection, "
                "competition law, sustainability, HR/legal, operational process errors, ethics "
                "& conduct, staff adequacy, business & strategy risks.",
                "No structured operational loss data surfaced in pre-mission tools.",
                "Request local incident logs, complaints, HR case statistics, compliance alerts.",
                "Use interviews and walkthroughs to identify non-quantified or emerging risks.",
            ],
            "methodology_stance": [
                "No mission-specific 'methodo' is registered; apply standard internal audit "
                "methodology.",
                "Risk-based scoping within the defined entity perimeter.",
                "Process mapping for key activities (rentals, entity management, HR, compliance).",
                "Control design and operating effectiveness testing.",
                "Sampling of client files, HR files, compliance cases, and asset files.",
                "Culture & conduct assessment via qualitative techniques (interviews, surveys, "
                "document review).",
            ],
            "historical_context": [
                "No previous recommendations identified for this exact combined scope.",
                "Treat this mission as a baseline review: document the current control "
                "environment and cultural posture.",
                "Generate initial recommendations that can be tracked in future cycles.",
            ],
            "open_questions": [
                "Which UK entities share a single HR and compliance function, and which operate "
                "standalone?",
                "Is there a local incident log outside the group operational-loss database?",
                "Who owns residual-value setting and remarketing decisions across the eight "
                "entities?",
            ],
        },
    },
    AYVENS_DE: {
        "mission_metadata": {
            "mission_id": AYVENS_DE,
            "mission_name": "2026_Ayvens Germany - Remarketing & Residual Value Management",
            "brief_scope": (
                "Thematic review of the remarketing chain and residual-value governance "
                "following the 2025 used-car price correction."
            ),
            "main_business_line": "AVNS/DE/IBFS/ALDA/LPDE/DEU/FIN",
            "countries": ["GERMANY"],
            "entities": _DE_ENTITIES,
            "risk_families": [
                "Risks related to operating leasing activities",
                "Errors in operating processes",
                "Business & Strategy risks",
                "Data protection",
                "Sustainability risks",
            ],
            "activities": [
                {"code": "A03.03.03", "label": "Rentals with/without Purchase Option"},
                {
                    "code": "A04",
                    "label": "Asset lifecycle",
                    "children": [
                        {"code": "A04.02", "label": "Residual value setting"},
                        {"code": "A04.05", "label": "Remarketing & disposal"},
                    ],
                },
            ],
            "business_lines": [
                "AVNS/DE/IBFS/ALDA/LPDE/DEU/FIN",
                "AVNS/DE/IBFS/ALDA/LPDE/DEU/REMKT",
            ],
            "audit_cycle": "2026 — thematic",
        },
        "scope_understanding": {
            "mission_name": "2026_Ayvens Germany - Remarketing & Residual Value Management",
            "brief_scope": (
                "Thematic review of remarketing and residual-value governance across the "
                "German leasing entities."
            ),
            "primary_scope_driver": "Process-driven",
            "scope_coverage": "Approximate",
            "missing_dimensions": [
                "Time period is not stated in the mission brief; assumed FY2024-FY2025.",
                "Unclear whether the captive dealer network is in scope for disposal channels.",
            ],
            "entity_filter": _DE_ENTITIES,
            "activity_filter": [
                "A04.02 — Residual value setting",
                "A04.05 — Remarketing & disposal",
            ],
            "risk_filter": [
                "Risks related to operating leasing activities",
                "Errors in operating processes",
            ],
            "reasoning": [
                "The mission title names two processes explicitly, so the process axis is the "
                "primary driver rather than the entity list.",
                "The entity filter still applies as a secondary constraint (German entities only).",
                "Coverage is marked approximate because the disposal-channel boundary is not "
                "settled in the brief.",
            ],
        },
        "risk_events": {
            "total_count": 4,
            "total_amount": 1_847_000.0,
            "currency": "EUR",
            "period": "2024-01-01 to 2026-06-30",
            "events": [
                {
                    "event_id": "OPL-2024-3312",
                    "title": "Residual value write-down on EV sub-fleet",
                    "entity": "ALD AUTOMOTIVE GMBH",
                    "event_date": "2024-09-30",
                    "risk_category": "Risks related to operating leasing activities",
                    "gross_amount": 1_210_000.0,
                    "net_amount": 1_210_000.0,
                    "currency": "EUR",
                    "status": "Closed",
                    "description": (
                        "RV curves for a 340-vehicle EV sub-fleet were not refreshed after the "
                        "Q2 2024 market correction, producing a one-off write-down at contract end."
                    ),
                },
                {
                    "event_id": "OPL-2025-0148",
                    "title": "Duplicate disposal invoices to auction partner",
                    "entity": "AYVENS REMARKETING GMBH",
                    "event_date": "2025-02-11",
                    "risk_category": "Errors in operating processes",
                    "gross_amount": 318_500.0,
                    "net_amount": 96_200.0,
                    "currency": "EUR",
                    "status": "Closed",
                    "description": (
                        "A batch re-run in the disposal platform issued duplicate invoices; "
                        "70% recovered from the partner within the quarter."
                    ),
                },
                {
                    "event_id": "OPL-2025-0771",
                    "title": "Damage recharge not billed at fleet return",
                    "entity": "LEASEPLAN DEUTSCHLAND GMBH",
                    "event_date": "2025-06-04",
                    "risk_category": "Errors in operating processes",
                    "gross_amount": 214_000.0,
                    "net_amount": 214_000.0,
                    "currency": "EUR",
                    "status": "Open",
                    "description": (
                        "End-of-contract damage assessments for one corporate client were not "
                        "transferred to billing for eleven months."
                    ),
                },
                {
                    "event_id": "OPL-2026-0042",
                    "title": "Late de-registration penalties",
                    "entity": "AYVENS REMARKETING GMBH",
                    "event_date": "2026-01-22",
                    "risk_category": "Errors in operating processes",
                    "gross_amount": 104_500.0,
                    "net_amount": 104_500.0,
                    "currency": "EUR",
                    "status": "Open",
                    "description": (
                        "Vehicles sold at auction were de-registered after the statutory window, "
                        "triggering administrative penalties."
                    ),
                },
            ],
            "interpretation": [
                "Losses concentrate on the remarketing chain rather than on contract origination.",
                "Two of four events remain open, so the control weakness is not yet remediated.",
                "The single largest loss is a residual-value governance failure, which aligns "
                "directly with the mission's primary process axis.",
            ],
        },
        "methodology": {
            "found": True,
            "message": "1 registered methodology matched this scope",
            "references": [
                {
                    "ref_id": "METH-LEAS-014",
                    "title": "Residual value governance and remarketing controls",
                    "version": "v3.1 (2025-04)",
                    "url": "https://intranet.example/audit/methodo/METH-LEAS-014",
                    "summary": (
                        "Standard programme for RV curve setting, challenge and back-testing, "
                        "plus disposal-channel controls and auction partner oversight."
                    ),
                    "scope_match": "High — process and entity axes both matched",
                },
            ],
            "implications": [
                "A registered methodology exists; use it as the testing backbone rather than "
                "building a programme from scratch.",
                "Version 3.1 postdates the 2025 market correction and already covers EV residual "
                "values.",
            ],
            "recommended_approach": [
                "Follow METH-LEAS-014 sections 2 (RV setting) and 4 (disposal controls).",
                "Extend the sample to cover the EV sub-fleet specifically, given OPL-2024-3312.",
            ],
        },
        "historical_recommendations": {
            "found": True,
            "message": "2 recommendations found on the perimeter",
            "recommendations": [
                {
                    "rec_id": "REC-2023-0219",
                    "title": "Formalise quarterly residual-value challenge committee",
                    "mission_ref": "23-IRB/AYVENS-007",
                    "entity": "ALD AUTOMOTIVE GMBH",
                    "risk_family": "Risks related to operating leasing activities",
                    "criticality": "High",
                    "status": "Open",
                    "due_date": "2025-12-31",
                    "description": (
                        "The 2023 review found RV assumptions were revised by the pricing team "
                        "without independent challenge. Overdue by more than one cycle."
                    ),
                    "source": "backend",
                },
                {
                    "rec_id": "REC-2024-0455",
                    "title": "Reconcile disposal platform invoices to the general ledger monthly",
                    "mission_ref": "24-IRB/AYVENS-012",
                    "entity": "AYVENS REMARKETING GMBH",
                    "risk_family": "Errors in operating processes",
                    "criticality": "Medium",
                    "status": "Closed",
                    "due_date": "2025-06-30",
                    "description": "Closed in Q3 2025; effectiveness not yet re-tested.",
                    "source": "backend",
                },
            ],
            "implications": [
                "REC-2023-0219 is open and overdue, and it addresses the exact control that "
                "failed in OPL-2024-3312 — verify remediation status early.",
                "REC-2024-0455 is closed but never re-tested; include it in the sample.",
            ],
        },
        "briefing": {
            "objective": (
                "Review residual-value governance and the remarketing chain across the German "
                "leasing entities, following the 2025 used-car price correction and the "
                "residual-value write-down recorded in 2024."
            ),
            "thematic_axes": [
                {
                    "title": "Residual value setting and challenge",
                    "points": [
                        "How RV curves are set, who challenges them, and how often they are "
                        "refreshed against market data.",
                        "Whether the EV sub-fleet is modelled separately — OPL-2024-3312 "
                        "suggests it was not.",
                        "Back-testing of realised versus forecast residual values.",
                    ],
                },
                {
                    "title": "Remarketing and disposal controls",
                    "points": [
                        "Disposal channel selection and auction partner oversight.",
                        "Invoice-to-ledger reconciliation on the disposal platform.",
                        "De-registration timeliness and the penalties it drives.",
                    ],
                },
                {
                    "title": "End-of-contract billing",
                    "points": [
                        "Transfer of damage assessments from inspection to billing.",
                        "Ageing of unbilled damage recharges by client.",
                    ],
                },
            ],
            "risk_landscape": [
                "Losses concentrate on the remarketing chain rather than on origination.",
                "Two of four recorded events remain open.",
            ],
            "methodology_stance": [
                "Apply METH-LEAS-014 v3.1 as the testing backbone.",
            ],
            "historical_context": [
                "One open, overdue recommendation covers the control that failed in 2024.",
            ],
            "open_questions": [
                "Who owns the RV curve refresh cycle, and what triggers an off-cycle revision?",
                "Is the captive dealer network in scope as a disposal channel?",
                "Which period should the review cover — the brief does not say.",
            ],
        },
    },
}


def available_missions() -> list[tuple[str, str]]:
    """(mission_id, mission_name) for every bundled sample."""
    return [
        (mission_id, str(data["mission_metadata"].get("mission_name", "")))
        for mission_id, data in _MISSIONS.items()
    ]


# ---------------------------------------------------------------------------
# Context-aware derivations
# ---------------------------------------------------------------------------


def _scope_entities(context: dict[str, Any]) -> list[str]:
    """Entity filter as the analyst left it, falling back to metadata."""
    scope = context.get("scope_understanding") or {}
    entities = scope.get("entity_filter") or scope.get("entities") or []
    if entities:
        return [str(e) for e in entities]
    metadata = context.get("mission_metadata") or {}
    return [str(e) for e in metadata.get("entities", [])]


def _filter_by_scope(
    payload: dict[str, Any], context: dict[str, Any], list_key: str
) -> dict[str, Any]:
    """Drop records whose entity fell outside the analyst-validated perimeter.

    This is what makes mock mode honest: narrowing the scope in stage 2 really
    does change stages 3 and 5.
    """
    allowed = {e.upper() for e in _scope_entities(context)}
    if not allowed:
        return payload
    records = payload.get(list_key) or []
    kept = [
        r
        for r in records
        if str(r.get("entity", "")).upper() in allowed or not r.get("entity")
    ]
    if len(kept) == len(records):
        return payload
    out = dict(payload)
    out[list_key] = kept
    dropped = len(records) - len(kept)
    note = f"{dropped} record(s) excluded: entity outside the validated perimeter."
    key = "interpretation" if list_key == "events" else "implications"
    out[key] = [*payload.get(key, []), note]
    if list_key == "events":
        out["total_count"] = len(kept)
        out["total_amount"] = sum(float(r.get("gross_amount") or 0) for r in kept)
    return out


def _rebuild_briefing(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Re-derive the briefing sections that depend on validated upstream stages."""
    out = dict(payload)
    entities = _scope_entities(context)
    if entities:
        out["perimeter"] = entities

    events = (context.get("risk_events") or {}).get("events") or []
    if events:
        total = sum(float(e.get("gross_amount") or 0) for e in events)
        open_events = [e for e in events if str(e.get("status", "")).lower() == "open"]
        out["risk_landscape"] = [
            f"{len(events)} operational loss event(s) in the validated perimeter, "
            f"{total:,.0f} gross.",
            f"{len(open_events)} still open — confirm remediation status before fieldwork.",
            *[str(i) for i in (context.get("risk_events") or {}).get("interpretation", [])],
        ]

    recs = (context.get("historical_recommendations") or {}).get("recommendations") or []
    if recs:
        closed = {"closed", "done", "implemented", "cancelled"}
        open_recs = [r for r in recs if str(r.get("status", "")).lower() not in closed]
        out["historical_context"] = [
            f"{len(recs)} prior recommendation(s) touch this perimeter; {len(open_recs)} open.",
            *[
                f"{r.get('rec_id', '?')} — {r.get('title', '')} ({r.get('status', 'unknown')})"
                for r in recs
            ],
        ]

    methodology = context.get("methodology") or {}
    refs = methodology.get("references") or []
    if refs:
        out["methodology_stance"] = [
            f"Registered methodology available: {r.get('ref_id', '')} — {r.get('title', '')}"
            for r in refs
        ] + [str(i) for i in methodology.get("recommended_approach", [])]
    return out


class MockAuditAgentClient:
    """Drop-in stand-in for :class:`~audit_front.client.HttpAuditAgentClient`."""

    label = "mock"

    def __init__(self, settings: Settings | None = None, *, latency: bool = True) -> None:
        self.settings = settings
        self._latency = latency
        self._counter = 0

    def health(self) -> HealthReport:
        return HealthReport(
            ok=True,
            detail=f"Mock backend — {len(_MISSIONS)} sample missions, no network calls",
            latency_ms=0.0,
            version="mock",
        )

    def run_stage(
        self,
        stage: StageSpec,
        mission_id: str,
        context: dict[str, Any],
        *,
        feedback: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> StageResponse:
        mission = _MISSIONS.get(mission_id.strip().upper())
        if mission is None:
            known = ", ".join(sorted(_MISSIONS))
            raise BackendError(
                f"Mission {mission_id!r} is not one of the bundled samples",
                status_code=404,
                detail=f"Mock mode knows: {known}. Point AUDIT_API_BASE_URL at the real "
                "backend and set AUDIT_BACKEND_MODE=live for other missions.",
            )

        if self._latency:
            time.sleep(random.uniform(0.5, 1.3))

        payload = _deep_copy(mission.get(stage.key, {}))
        if not payload:
            raise BackendError(
                f"The mock sample has no data for stage {stage.key!r}",
                status_code=501,
            )

        if stage.key == "risk_events":
            payload = _filter_by_scope(payload, context, "events")
        elif stage.key == "historical_recommendations":
            payload = _filter_by_scope(payload, context, "recommendations")
        elif stage.key == "briefing":
            payload = _rebuild_briefing(payload, context)

        warnings: list[str] = []
        if feedback:
            # Mirrors how a re-run reaches the agent: the instruction is visible
            # in the output, so the analyst can confirm it was taken into account.
            note = f"Re-run with analyst instruction: {feedback}"
            for key in ("reasoning", "interpretation", "implications"):
                if key in payload and isinstance(payload[key], list):
                    payload[key] = [*payload[key], note]
                    break
            else:
                warnings.append(note)

        if overrides:
            payload.update(overrides)

        self._counter += 1
        return StageResponse(
            payload=payload,
            warnings=warnings,
            trace_id=f"mock-{mission_id.split('/')[-1].lower()}-{stage.key}-{self._counter:03d}",
            raw={"status": "completed", "data": payload},
        )

    def close(self) -> None:  # parity with the HTTP client
        return None


def _deep_copy(value: Any) -> Any:
    import copy

    return copy.deepcopy(value)
