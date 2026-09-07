"""The live backend: HTTP implementation of the six APIs.

Each of the six methods below is a **placeholder wired to a sensible default**.
Today they all post to one templated endpoint (`AUDIT_API_STAGE_PATH`, with
`{stage}` substituted), which is what the assumed contract in
`docs/backend-contract.md` describes. When a real endpoint turns out to have a
different shape, you change *that one method* — the marked block inside it —
and nothing else moves.

Three helpers exist for exactly that edit:

* :meth:`HttpBackendAPI.post_stage` — the generic templated POST (current default)
* :meth:`HttpBackendAPI.get_json` — GET any path, e.g. a REST-style resource
* :meth:`HttpBackendAPI.post_json` — POST any path with any body

All three return a normalised :class:`~audit_front.api.StageResponse`, so the
UI is unaffected by which one a stage uses.

The envelope handling is deliberately forgiving: `{"data": …}`, `{"result": …}`,
a bare payload and an async job handle are all accepted, because the exact
response shape is not settled yet.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .api import BackendAPI, BackendError, HealthReport, StageRequest, StageResponse
from .config import Settings

# Envelope keys that wrap the real payload, in priority order.
_PAYLOAD_KEYS = ("data", "result", "payload", "output", "content")
_JOB_ID_KEYS = ("job_id", "jobId", "task_id", "taskId", "id")
_TRACE_KEYS = ("trace_id", "traceId", "request_id", "requestId", "correlation_id")
_PENDING_STATES = {"pending", "queued", "running", "in_progress", "processing", "accepted"}
_FAILED_STATES = {"failed", "error", "cancelled", "canceled", "timeout"}


# ---------------------------------------------------------------------------
# Envelope handling
# ---------------------------------------------------------------------------


def _first_key(body: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in body and body[key] not in (None, ""):
            return body[key]
    return None


def unwrap_payload(body: Any) -> dict[str, Any]:
    """Pull the stage payload out of whatever envelope the backend used."""
    if body is None:
        return {}
    if isinstance(body, list):
        return {"items": body}
    if not isinstance(body, dict):
        return {"value": body}

    for key in _PAYLOAD_KEYS:
        inner = body.get(key)
        if isinstance(inner, dict):
            return inner
        if isinstance(inner, list):
            return {"items": inner}
        if isinstance(inner, str) and inner.strip():
            # A stage that returns rendered markdown rather than structured data.
            return {"markdown": inner}

    # No envelope: the body *is* the payload. Drop transport-only keys so they
    # do not show up as phantom fields in the UI.
    transport = {"status", "state", "warnings", "errors", *_JOB_ID_KEYS, *_TRACE_KEYS}
    return {k: v for k, v in body.items() if k not in transport} or dict(body)


def extract_warnings(body: Any) -> list[str]:
    if not isinstance(body, dict):
        return []
    raw = body.get("warnings") or body.get("messages") or []
    if isinstance(raw, str):
        return [raw]
    return [str(w) for w in raw if str(w).strip()]


def extract_trace_id(body: Any, headers: Any = None) -> str | None:
    if isinstance(body, dict):
        value = _first_key(body, _TRACE_KEYS)
        if value:
            return str(value)
    if headers is not None:
        for header in ("X-Request-Id", "X-Trace-Id", "X-Correlation-Id"):
            if header in headers:
                return str(headers[header])
    return None


def _job_handle(body: Any) -> str | None:
    """Return a job id if the response is a handle rather than a payload."""
    if not isinstance(body, dict):
        return None
    state = str(body.get("status") or body.get("state") or "").lower()
    if state not in _PENDING_STATES:
        return None
    job_id = _first_key(body, _JOB_ID_KEYS)
    return str(job_id) if job_id else None


# ---------------------------------------------------------------------------
# HTTP implementation
# ---------------------------------------------------------------------------


class HttpBackendAPI(BackendAPI):
    """Talks to the real backend over HTTP."""

    label = "live"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.Client(
            timeout=httpx.Timeout(settings.timeout_s, connect=min(15.0, settings.timeout_s)),
            verify=settings.verify_ssl,
            headers={"Accept": "application/json", **settings.auth_headers()},
            follow_redirects=True,
        )

    # =====================================================================
    # The six backend APIs
    #
    # Each is a seam. Replace the body of the one whose endpoint you know;
    # leave the others on the generic default until their turn comes.
    # =====================================================================

    def fetch_mission_metadata(self, request: StageRequest) -> StageResponse:
        """Stage 1 — mission identity from the audit tooling.

        Assumed today::

            POST {AUDIT_API_STAGE_PATH}   with stage="mission_metadata"

        Runs from the mission code alone, so this is the likeliest of the six
        to be a plain resource read on the real backend.
        """
        # ── CONNECT THE REAL ENDPOINT HERE ─────────────────────────────────
        # e.g. a REST-style read:
        #     return self.get_json("/api/v1/missions/{mission_id}",
        #                          mission_id=request.mission_id)
        return self.post_stage(request)

    def analyse_mission_scope(self, request: StageRequest) -> StageResponse:
        """Stage 2 — the perimeter filter set, derived from the metadata.

        Assumed today::

            POST {AUDIT_API_STAGE_PATH}   with stage="scope_understanding"

        The request body carries the analyst-approved metadata under
        ``context.mission_metadata``; if the real endpoint wants it flattened,
        reshape it here.
        """
        # ── CONNECT THE REAL ENDPOINT HERE ─────────────────────────────────
        # e.g. a bespoke body:
        #     return self.post_json(
        #         "/api/v1/scope",
        #         {"mission": request.mission_id, "metadata": request.metadata},
        #     )
        return self.post_stage(request)

    def fetch_risk_events(self, request: StageRequest) -> StageResponse:
        """Stage 3 — operational-loss events on the validated perimeter.

        Assumed today::

            POST {AUDIT_API_STAGE_PATH}   with stage="risk_events"

        If the loss database is queried by entity list, ``request.entity_filter``
        is the validated perimeter, already reflecting any analyst edit.
        """
        # ── CONNECT THE REAL ENDPOINT HERE ─────────────────────────────────
        # e.g. a query against the loss database:
        #     return self.post_json(
        #         "/api/v1/losses/search",
        #         {"entities": request.entity_filter, "mission": request.mission_id},
        #     )
        return self.post_stage(request)

    def fetch_methodology(self, request: StageRequest) -> StageResponse:
        """Stage 4 — registered methodology matching this scope.

        Assumed today::

            POST {AUDIT_API_STAGE_PATH}   with stage="methodology"

        "Nothing registered" must come back as a payload, not a 404 — the UI
        presents it as a finding. If the real endpoint 404s on no-match, catch
        it here and return an empty payload instead.
        """
        # ── CONNECT THE REAL ENDPOINT HERE ─────────────────────────────────
        # e.g. tolerating a 404 as "none registered":
        #     try:
        #         return self.get_json("/api/v1/methodo", mission_id=request.mission_id)
        #     except BackendError as exc:
        #         if exc.status_code == 404:
        #             return self.empty_response(found=False)
        #         raise
        return self.post_stage(request)

    def fetch_historical_recommendations(self, request: StageRequest) -> StageResponse:
        """Stage 5 — recommendations raised on this perimeter in earlier cycles.

        Assumed today::

            POST {AUDIT_API_STAGE_PATH}   with stage="historical_recommendations"

        Same caveat as stage 4: an empty result is normal and must arrive as a
        payload.
        """
        # ── CONNECT THE REAL ENDPOINT HERE ─────────────────────────────────
        return self.post_stage(request)

    def build_briefing(self, request: StageRequest) -> StageResponse:
        """Stage 6 — synthesis of every validated stage.

        Assumed today::

            POST {AUDIT_API_STAGE_PATH}   with stage="briefing"

        The body carries all five upstream payloads *as the analyst approved
        them*, which is what makes the briefing reflect human review rather
        than the agent's first draft. Keep that if you reshape the request.
        """
        # ── CONNECT THE REAL ENDPOINT HERE ─────────────────────────────────
        # This stage is the likeliest to be long-running; if it returns a job
        # handle, `post_stage` already polls it to completion.
        return self.post_stage(request)

    # =====================================================================
    # Helpers for the edits above
    # =====================================================================

    def post_stage(self, request: StageRequest) -> StageResponse:
        """POST the generic stage endpoint — the default every method uses.

        ``AUDIT_API_STAGE_PATH`` with ``{mission_id}`` and ``{stage}``
        substituted, and :meth:`StageRequest.to_json` as the body.
        """
        url = self.settings.url_for(
            self.settings.stage_path,
            mission_id=request.mission_id,
            stage=request.stage_key,
        )
        return self._send("POST", url, json=request.to_json())

    def get_json(self, path_template: str, **params: str) -> StageResponse:
        """GET an arbitrary path and normalise the response.

        ``path_template`` is formatted with ``params``, e.g.
        ``get_json("/api/v1/missions/{mission_id}", mission_id=...)``.
        """
        return self._send("GET", self.settings.url_for(path_template, **params))

    def post_json(
        self, path_template: str, body: dict[str, Any], **params: str
    ) -> StageResponse:
        """POST an arbitrary body to an arbitrary path and normalise the response."""
        return self._send("POST", self.settings.url_for(path_template, **params), json=body)

    @staticmethod
    def empty_response(**payload: Any) -> StageResponse:
        """A well-formed empty result, for endpoints that signal 'none' with a 404."""
        return StageResponse(payload=dict(payload), raw={"status": "completed", "data": payload})

    # -- transport ---------------------------------------------------------

    def health(self) -> HealthReport:
        url = self.settings.url_for(self.settings.health_path)
        started = time.perf_counter()
        try:
            response = self._client.get(url, timeout=10.0)
        except httpx.HTTPError as exc:
            return HealthReport(ok=False, detail=f"{type(exc).__name__}: {exc}")
        latency = (time.perf_counter() - started) * 1000
        if response.status_code >= 400:
            return HealthReport(
                ok=False, detail=f"HTTP {response.status_code} from {url}", latency_ms=latency
            )
        version = None
        try:
            body = response.json()
            if isinstance(body, dict):
                version = body.get("version") or body.get("build")
        except ValueError:
            pass
        return HealthReport(ok=True, detail="Reachable", latency_ms=latency, version=version)

    def close(self) -> None:
        self._client.close()

    def _send(self, method: str, url: str, **kwargs: Any) -> StageResponse:
        """Request, await any job, and normalise — shared by all three helpers."""
        response = self._request(method, url, **kwargs)
        parsed = self._json(response, url)

        job_id = _job_handle(parsed)
        if job_id:
            parsed = self._await_job(job_id, url)

        self._raise_on_reported_failure(parsed, url)
        return StageResponse(
            payload=unwrap_payload(parsed),
            warnings=extract_warnings(parsed),
            trace_id=extract_trace_id(parsed, response.headers),
            raw=parsed if isinstance(parsed, dict) else {"body": parsed},
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """One request with retries on transport errors and transient statuses."""
        attempts = max(1, self.settings.max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if response.status_code < 400:
                    return response
                if response.status_code in (408, 429) or response.status_code >= 500:
                    last_error = BackendError(
                        "Backend returned a transient error",
                        status_code=response.status_code,
                        detail=_short_body(response),
                        url=url,
                    )
                else:
                    raise BackendError(
                        _status_message(response.status_code),
                        status_code=response.status_code,
                        detail=_short_body(response),
                        trace_id=extract_trace_id(None, response.headers),
                        url=url,
                    )
            if attempt < attempts - 1:
                time.sleep(min(2.0 * (2**attempt), 10.0))

        if isinstance(last_error, BackendError):
            raise last_error
        raise BackendError(
            "Could not reach the backend",
            detail=f"{type(last_error).__name__}: {last_error}",
            url=url,
        )

    def _json(self, response: httpx.Response, url: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise BackendError(
                "Backend response was not JSON",
                status_code=response.status_code,
                detail=_short_body(response),
                url=url,
            ) from exc

    def _await_job(self, job_id: str, origin_url: str) -> Any:
        """Poll an async job until it settles or the stage timeout elapses."""
        job_url = self.settings.url_for(self.settings.job_path, job_id=job_id)
        deadline = time.monotonic() + self.settings.timeout_s
        while time.monotonic() < deadline:
            time.sleep(self.settings.poll_interval_s)
            response = self._request("GET", job_url)
            body = self._json(response, job_url)
            if _job_handle(body):
                continue  # still pending
            return body
        raise BackendError(
            "Backend job did not finish in time",
            detail=f"job {job_id} still pending after {self.settings.timeout_s:.0f}s",
            url=origin_url,
        )

    @staticmethod
    def _raise_on_reported_failure(body: Any, url: str) -> None:
        if not isinstance(body, dict):
            return
        state = str(body.get("status") or body.get("state") or "").lower()
        if state in _FAILED_STATES:
            detail = body.get("error") or body.get("message") or body.get("detail")
            raise BackendError(
                "Backend reported the stage as failed",
                detail=str(detail) if detail else None,
                trace_id=extract_trace_id(body),
                url=url,
            )


def _short_body(response: httpx.Response, limit: int = 400) -> str:
    text = (response.text or "").strip().replace("\n", " ")
    return text[:limit] + ("…" if len(text) > limit else "")


def _status_message(status_code: int) -> str:
    return {
        400: "The backend rejected the request",
        401: "Not authenticated with the backend",
        403: "Not authorised for this mission",
        404: "Mission or stage not found on the backend",
        422: "The backend could not process the request payload",
    }.get(status_code, "The backend returned an error")
