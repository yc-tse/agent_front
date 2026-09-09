# agent-audit-front

Streamlit front-end for the internal-audit **mission-preparation agent**.

An auditor enters a mission code; the agent runs the pipeline against it; the
auditor reviews, edits and approves each stage before it feeds the next. The
output is a pre-mission briefing pack plus a record of exactly what the agent
produced and what the human changed.

The backend is not in this repository (internal policy). This app talks to it
through a **named method per backend API** (see *Connecting the real backend*),
each currently served by bundled **example data** — so it runs, demos and
develops today, and each endpoint gets connected the day it ships.

---

## Quick start

```bash
uv venv --python 3.13
uv pip install -e ".[dev]"
```

```bash
.venv/Scripts/streamlit run app.py
```

Or, on Windows:

```bash
.\run.ps1
```

It opens at <http://localhost:8501> serving **example data** — pick one of the
two bundled sample missions in the sidebar and walk the pipeline.

To point it at the real backend:

```bash
cp .env.example .env      # then set AUDIT_API_BASE_URL and AUDIT_BACKEND_MODE=live
```

You can also flip mode and base URL at runtime from the sidebar's
**Connection** panel, which is handy when the backend is intermittent.

---

## The stages

| # | Stage | What it produces | What the auditor checks |
|---|---|---|---|
| 1 | Mission metadata | Name, brief scope, entities, risk families, activity tree, business lines | Reference data goes stale — an entity missing here is missing everywhere after |
| 2 | Mission scope understanding | The **filter set** used by every later stage | The critical checkpoint: too broad and you drown in noise, too narrow and you miss losses that belong in scope |
| 3 | Operational risk events in scope | Loss events on the validated perimeter | An empty result is a finding, not a failure; exclude events that don't belong |
| 4 | Methodology references | Registered "methodo" for this scope, or the standard fallback | Add methodology notes held locally — the register is not exhaustive |
| 5 | Historical 3LOD reports | Prior 1/2/3LOD and external reports, their key messages, and the **IGAD positions** taken | Force in reports the search missed; exclude ones whose position doesn't bear on this mission |
| 6 | Historical recommendations | Prior recommendations on the perimeter | The search keys on this mission ID; recommendations from narrower prior missions won't appear |
| 7 | Consolidated pre-mission briefing | The deliverable | Edit it as your own document |

Stage 2 gates everything downstream. Editing it marks stages 3–7 **stale**, and
the UI says so rather than leaving a briefing built on a perimeter that no
longer holds.

Stages 5 and 6 answer different questions and are kept apart deliberately:
**what has already been said** about this perimeter, and **what was already
asked for**. A mission that contradicts a position IGAD took eighteen months
ago needs to know at scoping, not at the clearance meeting — so IGAD positions
get their own section, and both stages feed the briefing's historical context.

---

## How the human-in-the-loop actually works

Three properties make the review real rather than decorative:

1. **The analyst's version is what flows downstream.** Narrow the entity
   filter in stage 2 and stage 3 is *called* with the narrowed filter. The
   example backend honours this too, so it is demonstrable offline.

2. **Agent output and analyst output are stored separately.** An edit never
   overwrites `ai_payload`; it writes `analyst_payload`. The export can always
   answer *"what did the agent say, and what did the human change?"* — the
   question an audit department will be asked about an AI-assisted deliverable.

3. **Every transition is recorded.** Runs, edits, re-run instructions,
   approvals with notes, exclusions, and downstream invalidations all land in
   the audit trail, which ships inside both exports.

Each stage offers three responses: **approve** (optionally with a note),
**edit then approve**, or **ask the agent again** with a written instruction
(sent to the backend as `analyst_feedback`).

The sidebar's **Draft run** executes every outstanding stage back to back and
leaves all of them awaiting review. Nothing is ever auto-approved.

---

## Exports

- **Markdown** — the readable pack, in the same sections as the agent's
  own output, with a provenance appendix. Full pack or briefing only.
- **JSON** — the complete record: both payloads per stage, staleness, timings,
  trace IDs, and the audit trail.

See **[docs/example-export.md](docs/example-export.md)** for a full worked
example, generated from the bundled sample mission with two analyst edits
applied (`scripts/make_example_export.py` regenerates it).

---

## Connecting the real backend

`src/audit_front/api.py` is the integration surface: **one method per backend
sub-component**, so each endpoint is connected independently.

| Stage | Method |
|---|---|
| 1. Mission metadata | `fetch_mission_metadata` |
| 2. Mission scope understanding | `analyse_mission_scope` |
| 3. Operational risk events in scope | `fetch_risk_events` |
| 4. Methodology references | `fetch_methodology` |
| 5. Historical 3LOD reports | `fetch_historical_reports` |
| 6. Historical recommendations | `fetch_historical_recommendations` |
| 7. Consolidated pre-mission briefing | `build_briefing` |

Two implementations ship: `HttpBackendAPI` (`client.py`) and `ExampleDataAPI`
(`example_backend.py`). Every live method currently posts to one templated
endpoint and carries a marked block showing exactly what to replace:

```python
def fetch_risk_events(self, request: StageRequest) -> StageResponse:
    # ── CONNECT THE REAL ENDPOINT HERE ─────────────────────────────────
    #     return self.post_json(
    #         "/api/v1/losses/search",
    #         {"entities": request.entity_filter, "mission": request.mission_id},
    #     )
    return self.post_stage(request)
```

**The stage APIs can go live one at a time.** Name the ones that are ready and
the rest keep serving example data:

```
AUDIT_LIVE_STAGES=mission_metadata,scope_understanding
```

The sidebar's **Connection** panel does the same at runtime, so a new endpoint
can be tried without a restart. Mixed sessions are labelled throughout — a chip
on the stage header, a line per stage in the Markdown export, a `source` field
in the JSON, and a banner naming any section that came from example data.

To check a payload's shape before writing any code, paste a real response into
the mission file under `stages.<stage_key>` — the UI re-reads it on the next
run, and it becomes a regression fixture afterwards. See *Example missions*
below.

Endpoints are configuration templates, so a different routing scheme needs no
code change at all:

```
AUDIT_API_STAGE_PATH=/api/v1/missions/{mission_id}/stages/{stage}
AUDIT_API_HEALTH_PATH=/health
AUDIT_API_JOB_PATH=/api/v1/jobs/{job_id}
```

See **[docs/backend-contract.md](docs/backend-contract.md)** for the full
contract, the accepted key spellings, and what to change if the real API
differs.

---

## Example missions

**One mission is one file.** Everything about a sample — its id, its name, and
every stage payload from the metadata through to the briefing — lives in a
single document under `src/audit_front/example_data/`:

```json
{
  "mission_id": "26-IRB/AYVENS-019",
  "mission_name": "2026_Ayvens United Kingdom — Asset Risk, HR, Compliance…",
  "stages": {
    "mission_metadata":           { "entities": ["…"], "…": "…" },
    "scope_understanding":        { "entity_filter": ["…"], "…": "…" },
    "risk_events":                { "events": [], "…": "…" },
    "methodology":                { "found": false, "…": "…" },
    "historical_reports":         { "reports": [], "…": "…" },
    "historical_recommendations": { "recommendations": [], "…": "…" },
    "briefing":                   { "objective": "…", "…": "…" }
  }
}
```

The directory is the registry — **no mission is named anywhere in the code**.
Adding one means dropping a file in; there is nothing to register and nothing
to redeploy. Missions are keyed on the `mission_id` *inside* the document, so
the filename is yours to choose (`ayvens-uk.json` works as well as
`26-IRB_AYVENS-019.json`).

Two bundled samples take deliberately opposite paths: `26-IRB/AYVENS-019`
returns several empty result sets (reproducing the output that shaped this UI),
while `26-IRB/AYVENS-021` returns loss events, a matched methodology, prior
recommendations and an adverse 3LOD position.

Payloads are re-read on every call, so pasting a captured backend response into
`stages.<stage_key>` shows up on the next run without a restart. A file that is
unreadable or has no `mission_id` is skipped rather than breaking the app — and
named in the error message, so it does not vanish silently.

---

## Project layout

```
app.py                     Streamlit entry point
src/audit_front/
  api.py                   ★ the integration surface: one method per backend API
  client.py                Live implementation — HTTP, envelopes, job polling
  example_backend.py       Example implementation — scans the directory below
  example_data/            One JSON file per mission (see Example missions)
  routing.py               Which stages are live, which are on example data
  config.py                Settings from Streamlit secrets / env / .env
  models.py                Tolerant pydantic views over backend payloads
  pipeline.py              The stages: order, dependencies, purpose, API method
  state.py                 Session, stage runs, audit trail  (no Streamlit)
  runner.py                Stage orchestration               (no Streamlit)
  diffing.py               "Did the analyst actually change anything?"
  exporters.py             Markdown and JSON exports
  ui/                      Streamlit layer only
    stages/                One module per stage, plus the shared frame
tests/                     271 tests, no network, no browser
docs/backend-contract.md   What this app expects from the backend
docs/example-export.md     A worked example of the deliverable
scripts/                   Regenerates the example export
```

Everything outside `ui/` is deliberately Streamlit-free, so the interesting
behaviour is testable without a UI.

---

## Development

```bash
.venv/Scripts/python -m pytest          # 271 tests, ~12s
.venv/Scripts/python -m ruff check .    # line-length 100, target py311
```

`tests/test_app_smoke.py` renders **every view of the real app** through
Streamlit's `AppTest` — both sample missions, every stage, unapproved and
failed states, and malformed payloads. It catches the class of bug unit tests
miss (an invalid icon, a widget key collision, a renderer assuming a field
exists) and runs without a browser.

---

## Notes for whoever picks this up

- **Empty results are results.** Several stages routinely return
  nothing; the UI states what that means for fieldwork instead of showing a
  blank area. Don't "fix" those by hiding the section.
- **The models are tolerant on purpose.** Every field is optional, unknown
  keys are kept and shown under *Additional backend fields*, and `MissionName`
  / `missionName` / `mission_name` / `"Mission ID"` all resolve to the same
  field. A backend change should degrade the UI, never break it.
- **Adding a stage is a one-line change** in `pipeline.py` plus a renderer in
  `ui/stages/`. Order, dependencies and navigation all derive from that table.
