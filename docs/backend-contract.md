# Backend contract

What `agent-audit-front` sends, what it accepts back, and what to change if
the real API differs. Written as an **adapter spec**, not a mandate — the
front-end is built to bend toward the backend rather than the other way round.

---

## 1. Endpoints

All three are templates in configuration (`.env` / Streamlit secrets), so
routing differences need no code change.

| Setting | Default | Purpose |
|---|---|---|
| `AUDIT_API_STAGE_PATH` | `/api/v1/missions/{mission_id}/stages/{stage}` | Run one stage (POST) |
| `AUDIT_API_HEALTH_PATH` | `/health` | Reachability probe (GET) |
| `AUDIT_API_JOB_PATH` | `/api/v1/jobs/{job_id}` | Poll an async job (GET) |

`{stage}` takes one of the six keys, in pipeline order:

```
mission_metadata
scope_understanding
risk_events
methodology
historical_recommendations
briefing
```

Authentication is `none`, `bearer` (`Authorization: Bearer …`) or `api_key`
(a configurable header, default `X-API-Key`).

---

## 2. Request

```jsonc
POST /api/v1/missions/26-IRB%2FAYVENS-019/stages/risk_events
{
  "mission_id": "26-IRB/AYVENS-019",
  "stage": "risk_events",
  "requested_by": "r.doe",

  // Analyst-validated output of this stage's dependencies.
  // This is the human-in-the-loop channel: if the auditor narrowed the
  // entity filter in stage 2, the narrowed filter arrives here.
  "context": {
    "scope_understanding": {
      "primary_scope_driver": "Entity-driven",
      "entity_filter": ["ALD AUTOMOTIVE LIMITED", "LEASEPLAN UK LIMITED"],
      "...": "..."
    }
  },

  // Present only when the analyst pressed "Ask the agent again".
  "analyst_feedback": "Treat this as process-driven and keep only leasing entities.",

  // Reserved; unused by the current UI.
  "overrides": {}
}
```

Dependencies per stage:

| Stage | `context` contains |
|---|---|
| `mission_metadata` | — |
| `scope_understanding` | `mission_metadata` |
| `risk_events` | `scope_understanding` |
| `methodology` | `scope_understanding` |
| `historical_recommendations` | `scope_understanding` |
| `briefing` | all five |

---

## 3. Response

Any of these is accepted:

```jsonc
{"status": "completed", "data": { /* payload */ }, "warnings": [], "trace_id": "…"}
{"result": { /* payload */ }}
{ /* the payload itself, unwrapped */ }
{"data": "# Rendered markdown"}            // becomes {"markdown": "…"}
```

Async is detected automatically — a response whose `status`/`state` is one of
`pending`, `queued`, `running`, `in_progress`, `processing`, `accepted` **and**
which carries `job_id` / `jobId` / `task_id` / `id` is polled at
`AUDIT_API_JOB_PATH` until it settles or `AUDIT_API_TIMEOUT_S` elapses.

A `status`/`state` of `failed`, `error`, `cancelled` or `timeout` is surfaced
as a stage error with `error` / `message` / `detail` shown to the analyst.

Trace IDs are read from `trace_id` / `traceId` / `request_id` / `requestId` /
`correlation_id`, or the `X-Request-Id` / `X-Trace-Id` / `X-Correlation-Id`
headers. They are displayed on the stage and carried into both exports.

Retries: transport errors, `408`, `429` and `5xx` are retried
`AUDIT_API_MAX_RETRIES` times with exponential backoff. `4xx` (other than the
two above) fails immediately with a message naming the likely cause.

---

## 4. Payload shapes

Every field is optional. Unknown fields are preserved and shown in the UI
under *Additional backend fields*. Key spellings are normalised, so
`MissionName`, `missionName`, `mission_name` and `"Mission Name"` are the same
field; the **Accepts** column lists spellings that do *not* normalise on their
own.

### `mission_metadata`

| Field | Type | Accepts |
|---|---|---|
| `mission_id` | string | `id`, `code`, `mission_code` |
| `mission_name` | string | `name` |
| `brief_scope` | string | `scope` |
| `main_business_line` | string | `primary_business_line` |
| `countries` | string[] | `country` |
| `entities` | string[] | `entities_in_scope`, `entity_list` |
| `risk_families` | string[] | `RiskL1`, `key_risk_families`, `risks` |
| `activities` | tree | `ActivityThree`, `main_activities`, `processes` |
| `business_lines` | string[] | `business_lines_involved` |
| `audit_cycle`, `planned_start`, `planned_end` | string | |

`activities` accepts nested `{code, label, children[]}` objects *or* plain
strings like `"A22.01.01 - AML"`, which are split into code and label.

### `scope_understanding`

| Field | Type | Accepts |
|---|---|---|
| `primary_scope_driver` | string | `driver`, `scope_driver` |
| `scope_coverage` | string | `coverage` |
| `missing_dimensions` | string[] | |
| `entity_filter` | string[] | `entities` |
| `country_filter` / `risk_filter` / `activity_filter` / `business_line_filter` | string[] | `countries`, `risks`, `activities`, `business_lines` |
| `reasoning` | string[] | `rationale`, `justification` |

The UI errors loudly if no filter dimension is set, because every later stage
would then run against the whole population.

### `risk_events`

| Field | Type | Accepts |
|---|---|---|
| `events` | object[] | `losses`, `operational_losses`, `items`, `results` |
| `total_count`, `total_amount`, `currency`, `period` | | `count` |
| `interpretation` | string[] | `analysis`, `comment` |

Event: `event_id` (`id`, `reference`), `title`, `entity`, `event_date`
(`date`), `risk_category` (`RiskL1`, `category`), `gross_amount` (`amount`),
`net_amount`, `currency`, `status`, `description`.

`"events": {}`, `[]` and `null` all mean *no losses surfaced*, which the UI
presents as a finding rather than as an empty panel.

### `methodology`

| Field | Type | Accepts |
|---|---|---|
| `found` | bool | inferred from `references` when absent |
| `references` | object[] | `methodo`, `methodologies`, `items` |
| `message` | string | `result`, `methodology_result` |
| `implications`, `recommended_approach` | string[] | `approach` |

Reference: `ref_id`, `title`, `version`, `url` (`link`), `summary`,
`scope_match` (`relevance`).

### `historical_recommendations`

| Field | Type | Accepts |
|---|---|---|
| `found` | bool | inferred from `recommendations` when absent |
| `recommendations` | object[] | `items`, `previous_recommendations` |
| `message` | string | `result`, `recommendations_result` |
| `implications` | string[] | |

Recommendation: `rec_id` (`id`), `title`, `mission_ref` (`mission_id`),
`entity`, `risk_family` (`RiskL1`), `criticality` (`severity`, `priority`),
`status` (`state`), `due_date` (`deadline`), `description`.

Statuses `closed`, `done`, `implemented` and `cancelled` count as closed.

### `briefing`

| Field | Type | Accepts |
|---|---|---|
| `objective` | string | `mission_objective`, `goal` |
| `perimeter` | string[] | `perimeter_to_use`, `entities` |
| `thematic_axes` | object[] | `key_thematic_axes`, `axes`, `themes` |
| `risk_landscape`, `methodology_stance`, `historical_context`, `open_questions` | string[] | `questions` |
| `markdown` | string | `text`, `content` |

Axis: `{title, points[]}`; a bare string becomes a title. A response that is
just a markdown string is accepted and rendered as-is.

**String lists are forgiving**: a newline-separated string is split into
items, and a scalar is wrapped into a one-item list.

---

## 5. Encoding note

The sample outputs that shaped this UI contained cp1252-decoded UTF-8
punctuation (`â€"` for an en dash, `â€™` for an apostrophe). The front-end
repairs these on the way in, so the backend team does not have to change
anything — but it does indicate a `latin-1`/`utf-8` mismatch somewhere
upstream that is worth finding at source.

---

## 6. Where to connect each API

`src/audit_front/api.py` defines the integration surface: **one method per
backend sub-component**. Connecting an endpoint is editing one method, not
threading a condition through shared code.

| Stage | Method | Lives in |
|---|---|---|
| 1. Mission metadata | `fetch_mission_metadata` | `client.py` (live) / `example_backend.py` |
| 2. Mission scope understanding | `analyse_mission_scope` | ” |
| 3. Operational risk events in scope | `fetch_risk_events` | ” |
| 4. Methodology references | `fetch_methodology` | ” |
| 5. Historical recommendations | `fetch_historical_recommendations` | ” |
| 6. Consolidated pre-mission briefing | `build_briefing` | ” |

Each live method today posts to the generic templated endpoint and carries a
marked block showing what to replace:

```python
def fetch_risk_events(self, request: StageRequest) -> StageResponse:
    # ── CONNECT THE REAL ENDPOINT HERE ─────────────────────────────────
    # e.g. a query against the loss database:
    #     return self.post_json(
    #         "/api/v1/losses/search",
    #         {"entities": request.entity_filter, "mission": request.mission_id},
    #     )
    return self.post_stage(request)
```

Three helpers cover the common shapes, all returning a normalised
`StageResponse` so the UI is unaffected by which one a stage uses:

- `post_stage(request)` — the generic templated POST (current default)
- `get_json(path_template, **params)` — GET a REST-style resource
- `post_json(path_template, body, **params)` — POST a bespoke body

`request` is a `StageRequest`, with accessors so implementations never dig
through raw dicts: `request.metadata`, `request.scope`, `request.entity_filter`
(the perimeter *as the analyst approved it*), `request.upstream(stage_key)`,
`request.feedback`, and `request.to_json()` for the standard body.

### Switching stages over one at a time

The six APIs will not ship together. `AUDIT_LIVE_STAGES` names the stages that
call the real backend; everything else keeps serving example data:

```
AUDIT_LIVE_STAGES=mission_metadata,scope_understanding
```

`all`, `none`, and an empty value (follow `AUDIT_BACKEND_MODE`) are also
accepted. The sidebar's **Connection** panel does the same thing at runtime,
so an endpoint can be tried without a restart.

Mixed sessions are labelled everywhere it matters — a chip on the stage
header, a line per stage in the Markdown export, a `source` field per stage in
the JSON export, and a banner naming any section that came from example data.
A pack built partly from example data must never read as a fully live one.

### Checking a new endpoint's shape before wiring it

Save a real response as `src/audit_front/example_data/<mission>/<stage>.json`
and the UI renders it immediately — no code, no redeploy. That is the quickest
way to see whether a payload fits the models in section 4, and it doubles as a
regression fixture afterwards.

---

## 7. If the real API differs

- **Different routes** → change the three path templates in configuration, or
  the single method for the one stage that differs (section 6).
- **Different envelope or auth flow** → `client.py`: `unwrap_payload` and
  `HttpBackendAPI._send`. Nothing else in the app talks HTTP.
- **Different field names** → add an entry to the relevant model's
  `key_aliases` in `models.py` (one line, keyed on the normalised spelling).
- **A new field you want rendered** → add it to the model and to that stage's
  module in `ui/stages/`. Until then it still shows under *Additional backend
  fields*, so nothing is silently dropped.
- **A seventh stage** → one `StageSpec` in `pipeline.py` (including its
  `api_method`), a matching method on `BackendAPI` and its two implementations,
  and a renderer. Order, dependencies, navigation, exports and staleness all
  derive from that entry.
