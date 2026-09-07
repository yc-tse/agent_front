# agent-audit-front

Streamlit front-end for the internal-audit **mission-preparation agent**.

An auditor enters a mission code; the agent runs six stages against it; the
auditor reviews, edits and approves each stage before it feeds the next. The
output is a pre-mission briefing pack plus a record of exactly what the agent
produced and what the human changed.

The backend is not in this repository (internal policy). This app talks to it
over HTTP, and ships with a **mock backend** so it runs, demos and develops
without one.

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

It opens at <http://localhost:8501> in **mock mode** — pick one of the two
bundled sample missions in the sidebar and walk the pipeline.

To point it at the real backend:

```bash
cp .env.example .env      # then set AUDIT_API_BASE_URL and AUDIT_BACKEND_MODE=live
```

You can also flip mode and base URL at runtime from the sidebar's
**Connection** panel, which is handy when the backend is intermittent.

---

## The six stages

| # | Stage | What it produces | What the auditor checks |
|---|---|---|---|
| 1 | Mission metadata | Name, brief scope, entities, risk families, activity tree, business lines | Reference data goes stale — an entity missing here is missing everywhere after |
| 2 | Mission scope understanding | The **filter set** used by every later stage | The critical checkpoint: too broad and you drown in noise, too narrow and you miss losses that belong in scope |
| 3 | Operational risk events in scope | Loss events on the validated perimeter | An empty result is a finding, not a failure; exclude events that don't belong |
| 4 | Methodology references | Registered "methodo" for this scope, or the standard fallback | Add methodology notes held locally — the register is not exhaustive |
| 5 | Historical recommendations | Prior recommendations on the perimeter | The search keys on this mission ID; recommendations from narrower prior missions won't appear |
| 6 | Consolidated pre-mission briefing | The deliverable | Edit it as your own document |

Stage 2 gates everything downstream. Editing it marks stages 3–6 **stale**,
and the UI says so rather than leaving a briefing built on a perimeter that no
longer holds.

---

## How the human-in-the-loop actually works

Three properties make the review real rather than decorative:

1. **The analyst's version is what flows downstream.** Narrow the entity
   filter in stage 2 and stage 3 is *called* with the narrowed filter. The
   mock backend honours this too, so the behaviour is demonstrable offline.

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

- **Markdown** — the readable pack, in the same six sections as the agent's
  own output, with a provenance appendix. Full pack or briefing only.
- **JSON** — the complete record: both payloads per stage, staleness, timings,
  trace IDs, and the audit trail.

See **[docs/example-export.md](docs/example-export.md)** for a full worked
example, generated from the bundled sample mission with two analyst edits
applied (`scripts/make_example_export.py` regenerates it).

---

## Connecting the real backend

Endpoints are templates in configuration, so a different routing scheme needs
no code change:

```
AUDIT_API_STAGE_PATH=/api/v1/missions/{mission_id}/stages/{stage}
AUDIT_API_HEALTH_PATH=/health
AUDIT_API_JOB_PATH=/api/v1/jobs/{job_id}
```

The client posts a small JSON body per stage and accepts several response
shapes (`{"data": …}`, `{"result": …}`, a bare payload, or an async job handle
it polls). See **[docs/backend-contract.md](docs/backend-contract.md)** for
the full contract, the accepted key spellings, and what to change if the real
API differs.

If it differs beyond what the adapter absorbs, `HttpAuditAgentClient.run_stage`
is the single method to rewrite — nothing else in the app talks HTTP.

---

## Project layout

```
app.py                     Streamlit entry point
src/audit_front/
  config.py                Settings from Streamlit secrets / env / .env
  models.py                Tolerant pydantic views over backend payloads
  pipeline.py              The six stages: order, dependencies, purpose
  state.py                 Session, stage runs, audit trail  (no Streamlit)
  runner.py                Stage orchestration               (no Streamlit)
  diffing.py               "Did the analyst actually change anything?"
  client.py                HTTP adapter: envelopes, retries, job polling
  mock_backend.py          Two bundled sample missions
  exporters.py             Markdown and JSON exports
  ui/                      Streamlit layer only
    stages/                One module per stage, plus the shared frame
tests/                     148 tests, no network, no browser
docs/backend-contract.md   What this app expects from the backend
docs/example-export.md     A worked example of the deliverable
scripts/                   Regenerates the example export
```

Everything outside `ui/` is deliberately Streamlit-free, so the interesting
behaviour is testable without a UI.

---

## Development

```bash
.venv/Scripts/python -m pytest          # 148 tests, ~11s
.venv/Scripts/python -m ruff check .    # line-length 100, target py311
```

`tests/test_app_smoke.py` renders **every view of the real app** through
Streamlit's `AppTest` — both sample missions, every stage, unapproved and
failed states, and malformed payloads. It catches the class of bug unit tests
miss (an invalid icon, a widget key collision, a renderer assuming a field
exists) and runs without a browser.

---

## Notes for whoever picks this up

- **Empty results are results.** Three of the six stages routinely return
  nothing; the UI states what that means for fieldwork instead of showing a
  blank area. Don't "fix" those by hiding the section.
- **The models are tolerant on purpose.** Every field is optional, unknown
  keys are kept and shown under *Additional backend fields*, and `MissionName`
  / `missionName` / `mission_name` / `"Mission ID"` all resolve to the same
  field. A backend change should degrade the UI, never break it.
- **Adding a stage is a one-line change** in `pipeline.py` plus a renderer in
  `ui/stages/`. Order, dependencies and navigation all derive from that table.
