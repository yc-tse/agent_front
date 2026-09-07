"""HTTP client for the mission-preparation backend.

The backend is not in this repository, so this module is written as an
*adapter*, not as a hard contract. Three things absorb the difference between
the assumed API and the real one:

1. **Endpoint templates live in config** (``AUDIT_API_STAGE_PATH`` etc.), so a
   different routing scheme needs no code change.
2. **Response envelopes are unwrapped heuristically** — ``{"data": {...}}``,
   ``{"result": {...}}`` and a bare payload are all accepted.
3. **Async jobs are detected and polled** — if a stage returns a job handle
   instead of a payload, the client waits it out.

If the real API differs beyond that, :meth:`HttpAuditAgentClient.run_stage`
is the one method to rewrite; nothing else in the app talks HTTP.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .config import Settings
from .pipeline import StageSpec

# Envelope keys that wrap the real payload, in priority order.
_PAYLOAD_KEYS = ("data", "result", "payload", "output", "content")
_JOB_ID_KEYS = ("job_id", "jobId", "task_id", "taskId", "id")
_TRACE_KEYS = ("trace_id", "traceId", "request_id", "requestId", "correlation_id")
_PENDING_STATES = {"pending", "queued", "running", "in_progress", "processing", "accepted"}
_FAILED_STATES = {"failed", "error", "cancelled", "canceled", "timeout"}


class BackendError(RuntimeError):
    """Any failure to obtain a usable stage payload.

    Carries enough context for the UI to show something an analyst can act on
    (and quote in a ticket) rather than a bare stack trace.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: str | None = None,
        trace_id: str | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail
        self.trace_id = trace_id
        self.url = url

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.append(f"HTTP {self.status_code}")
        if self.detail:
            parts.append(self.detail)
        if self.trace_id:
            parts.append(f"trace {self.trace_id}")
        return " · ".join(parts)


@dataclass
class StageResponse:
    """Normalised result of one stage call."""

    payload: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    trace_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthReport:
    ok: bool
    detail: str
    latency_ms: float | None = None
    version: str | None = None


class AuditAgentClient(Protocol):
    """What the UI needs from a backend — implemented by HTTP and mock clients."""

    label: str

    def health(self) -> HealthReport: ...

    def run_stage(
        self,
        stage: StageSpec,
        mission_id: str,
        context: dict[str, Any],
        *,
        feedback: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> StageResponse: ...


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


def build_request_body(
    stage: StageSpec,
    mission_id: str,
    context: dict[str, Any],
    *,
    feedback: str | None = None,
    overrides: dict[str, Any] | None = None,
    analyst: str = "unknown",
) -> dict[str, Any]:
    """The JSON body sent for every stage call.

    ``context`` carries the *analyst-validated* payloads of upstream stages,
    which is what makes the human-in-the-loop real: edits made in the UI reach
    the backend as the input for the next stage, not just as display state.
    """
    body: dict[str, Any] = {
        "mission_id": mission_id,
        "stage": stage.key,
        "context": context,
        "requested_by": analyst,
    }
    if feedback:
        body["analyst_feedback"] = feedback
    if overrides:
        body["overrides"] = overrides
    return body


# ---------------------------------------------------------------------------
# HTTP implementation
# ---------------------------------------------------------------------------


class HttpAuditAgentClient:
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

    # -- public API --------------------------------------------------------

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

    def run_stage(
        self,
        stage: StageSpec,
        mission_id: str,
        context: dict[str, Any],
        *,
        feedback: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> StageResponse:
        url = self.settings.url_for(
            self.settings.stage_path, mission_id=mission_id, stage=stage.key
        )
        body = build_request_body(
            stage,
            mission_id,
            context,
            feedback=feedback,
            overrides=overrides,
            analyst=self.settings.analyst,
        )
        response = self._request("POST", url, json=body)
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

    def close(self) -> None:
        self._client.close()

    # -- internals ---------------------------------------------------------

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


def build_client(settings: Settings) -> AuditAgentClient:
    """Pick the mock or HTTP client according to configuration."""
    if settings.is_mock:
        from .mock_backend import MockAuditAgentClient

        return MockAuditAgentClient(settings)
    return HttpAuditAgentClient(settings)
