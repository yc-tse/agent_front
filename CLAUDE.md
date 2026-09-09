# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## What this is

`agent-audit-front` is the **Streamlit front-end** for an internal-audit
mission-preparation agent. An auditor enters a mission code; the agent runs six
stages; the auditor reviews, edits and approves each stage before it feeds the
next. See `README.md` for the product view and
`docs/backend-contract.md` for the API seam.

**The backend is not in this repository** and cannot be. Everything here is
written to bend toward an API it cannot see — that constraint explains most of
the design decisions below.

## Commands

```bash
# Install
uv venv --python 3.13
uv pip install -e ".[dev]"

# Run (mock mode — no backend needed)
.venv/Scripts/streamlit run app.py
.\run.ps1                       # same, with -Live to hit the real backend

# Tests — no network, no browser
.venv/Scripts/python -m pytest
.venv/Scripts/python -m pytest tests/test_diffing.py -q      # one file
.venv/Scripts/python -m pytest -k "scope_propagation"        # one behaviour

# Lint (line-length 100, target py311)
.venv/Scripts/python -m ruff check .
```

Requires Python ≥ 3.11 and Streamlit ≥ 1.49 (for the `width=` layout API;
`use_container_width` is deprecated and must not be reintroduced).

## Architecture

A strict one-way pipeline with a human checkpoint between every step:

```
mission_metadata ─▶ scope_understanding ─┬─▶ risk_events ──────────────┐
                    (critical gate)      ├─▶ methodology ──────────────┤
                                         ├─▶ historical_reports ───────┼─▶ briefing
                                         └─▶ historical_recommendations┘
```

`pipeline.py` is the **single source of truth** for that shape — stage order,
dependencies, which model parses each payload, and the sentence shown to the
analyst at each checkpoint. The UI, client, runner and exporter all read from
it, so adding or renaming a stage is a one-line change plus a renderer.

The backend is reached through **one named method per sub-component**, declared
on each `StageSpec` as `api_method` and dispatched by `BackendAPI.run_stage`:

| Stage | Method |
|---|---|
| `mission_metadata` | `fetch_mission_metadata` |
| `scope_understanding` | `analyse_mission_scope` |
| `risk_events` | `fetch_risk_events` |
| `methodology` | `fetch_methodology` |
| `historical_reports` | `fetch_historical_reports` |
| `historical_recommendations` | `fetch_historical_recommendations` |
| `briefing` | `build_briefing` |

`historical_reports` (what has already been said about this perimeter, and the
IGAD positions taken) is deliberately separate from `historical_recommendations`
(what was already asked for). Both feed the briefing's historical context.

Read the modules in this order:

- **`pipeline.py`** — the six `StageSpec`s. Start here.
- **`api.py`** — the integration surface: `BackendAPI`, `StageRequest`,
  `StageResponse`, `BackendError`. Read before touching anything backend-facing.
- **`models.py`** — deliberately *tolerant* pydantic views. Every field
  optional, `extra="allow"`, and incoming keys normalised so `MissionName`,
  `missionName`, `mission_name` and `"Mission ID"` all land on the same field.
  A backend change should degrade the UI, never break it. `key_aliases` is
  where you add a spelling that doesn't normalise on its own. List coercion is
  derived from the annotations in `LooseModel._normalise_keys` and runs *after*
  key mapping — don't reintroduce per-model coercion validators, which coerced
  before the alias was resolved and so failed on `{"country": "UK"}`.
- **`state.py`** — `MissionSession` / `StageRun` / audit trail. Two ideas carry
  the whole design: **`ai_payload` and `analyst_payload` are separate** (an
  edit never destroys what the agent said), and **editing a stage marks its
  dependants stale** rather than leaving a briefing built on a dead perimeter.
- **`runner.py`** — orchestration. `run_stage` never raises; a backend failure
  becomes an ERROR state carrying a message the analyst can act on.
- **`diffing.py`** — "did the analyst actually change anything?" Harder than
  `before != after`; see the module docstring for why.
- **`client.py`** — the only module that talks HTTP. Each of the six methods is
  a seam carrying a `── CONNECT THE REAL ENDPOINT HERE ──` block; all six
  currently share `post_stage()`. Also envelope unwrapping, retries, job polling.
- **`example_backend.py`** — scans `example_data/` and serves what it finds.
  **One mission is one file**: `{mission_id, mission_name, stages{…}}`, keyed on
  the id *inside* the document, so the filename is free and adding a sample
  mission is dropping a file in. No mission is named anywhere in Python — if you
  find yourself adding a constant for one, that is the bug. Payloads are
  re-read per call, so editing a file while the app runs takes effect on the
  next run; the directory scan is cached (`reload_example_data()` to re-scan).
  Not decoration either: it honours `request.context`, so a scope edited in
  stage 2 really does change the later stages — including re-syncing the
  cross-report synthesis when reports leave the perimeter.
- **`routing.py`** — per-stage live/example selection (`AUDIT_LIVE_STAGES`), so
  the six APIs can be switched over one at a time.
- **`ui/`** — Streamlit only. `ui/stages/__init__.py` holds the frame every
  stage shares; each stage module renders content plus editors and **returns
  the draft payload**.

`state.py`, `runner.py`, `diffing.py`, `models.py` and `exporters.py` are
Streamlit-free on purpose, so the interesting behaviour is testable without a
UI. Keep it that way.

## Conventions that matter here

- **The analyst's version is what flows downstream.** `StageRun.payload`
  returns `analyst_payload` when present. Anything that consumes a stage
  output — `context_for`, the exporters, the next stage's request — must go
  through it, never through `ai_payload`.
- **Empty results are results.** Three of the six stages routinely return
  nothing. Render an `empty_state` explaining what the absence means for
  fieldwork; never hide the section.
- **Never silently drop backend data.** Unmodelled fields surface through
  `unmodelled_fields()`; the raw payload is always one expander away.
- **Never let example data pass for live data.** `StageResponse.source` is
  stamped by `run_stage` and carried to `StageRun.source`, the stage header
  chip, both exports and the audit trail. A pack that mixes the two says so on
  its first page.
- **Every state transition goes through a `MissionSession` method** so it
  lands in the audit trail. Don't mutate `StageRun` fields directly from the
  UI.

## Testing

`tests/test_app_smoke.py` renders **every view of the real app** with
Streamlit's `AppTest` — both sample missions × all six stages, unapproved and
failed states, empty and unrecognised payloads. It catches what unit tests
can't: an invalid `icon=` emoji, a widget key collision, a renderer assuming a
field exists. Run it after any UI change.

`tests/test_api_surface.py` guards the integration seams: every `api_method`
resolves to an abstract method that all implementations provide, `run_stage`
dispatches to the right one, and the router sends each stage to its configured
backend. Add a case there when you add a stage or an implementation.

`tests/test_diffing.py` guards a real bug: the editors rebuild the payload on
every render, so a naive comparison flagged "unsaved changes" before anyone
touched anything — which trains analysts to ignore the warning that matters.
