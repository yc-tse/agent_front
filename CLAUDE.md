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
                    (critical gate)      ├─▶ methodology ──────────────┼─▶ briefing
                                         └─▶ historical_recommendations┘
```

`pipeline.py` is the **single source of truth** for that shape — stage order,
dependencies, which model parses each payload, and the sentence shown to the
analyst at each checkpoint. The UI, client, runner and exporter all read from
it, so adding or renaming a stage is a one-line change plus a renderer.

Read the modules in this order:

- **`pipeline.py`** — the six `StageSpec`s. Start here.
- **`models.py`** — deliberately *tolerant* pydantic views. Every field
  optional, `extra="allow"`, and incoming keys normalised so `MissionName`,
  `missionName`, `mission_name` and `"Mission ID"` all land on the same field.
  A backend change should degrade the UI, never break it. `key_aliases` is
  where you add a spelling that doesn't normalise on its own.
- **`state.py`** — `MissionSession` / `StageRun` / audit trail. Two ideas carry
  the whole design: **`ai_payload` and `analyst_payload` are separate** (an
  edit never destroys what the agent said), and **editing a stage marks its
  dependants stale** rather than leaving a briefing built on a dead perimeter.
- **`runner.py`** — orchestration. `run_stage` never raises; a backend failure
  becomes an ERROR state carrying a message the analyst can act on.
- **`diffing.py`** — "did the analyst actually change anything?" Harder than
  `before != after`; see the module docstring for why.
- **`client.py`** — the only module that talks HTTP. Envelope unwrapping,
  retries, async job polling.
- **`mock_backend.py`** — two sample missions. Not decoration: it honours
  `context`, so a scope edited in stage 2 really does change stages 3–6.
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
- **Every state transition goes through a `MissionSession` method** so it
  lands in the audit trail. Don't mutate `StageRun` fields directly from the
  UI.

## Testing

`tests/test_app_smoke.py` renders **every view of the real app** with
Streamlit's `AppTest` — both sample missions × all six stages, unapproved and
failed states, empty and unrecognised payloads. It catches what unit tests
can't: an invalid `icon=` emoji, a widget key collision, a renderer assuming a
field exists. Run it after any UI change.

`tests/test_diffing.py` guards a real bug: the editors rebuild the payload on
every render, so a naive comparison flagged "unsaved changes" before anyone
touched anything — which trains analysts to ignore the warning that matters.
