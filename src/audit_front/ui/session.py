"""Binding between the pure-Python session model and Streamlit's runtime.

Keeps every ``st.session_state`` key in one place, so the rest of the UI reads
like ordinary Python rather than like string-keyed global state.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import streamlit as st

from ..client import AuditAgentClient, HealthReport, build_client
from ..config import Settings, get_settings
from ..pipeline import STAGE_KEYS
from ..state import MissionSession

_SESSION = "af_session"
_ACTIVE = "af_active_stage"
_OVERRIDES = "af_settings_overrides"
_VIEW = "af_view"  # "stage" | "briefing_pack" | "audit_trail"


# ---------------------------------------------------------------------------
# Settings (config file / env, with in-app overrides)
# ---------------------------------------------------------------------------


def settings_overrides() -> dict[str, Any]:
    return st.session_state.setdefault(_OVERRIDES, {})


def set_override(key: str, value: Any) -> None:
    overrides = settings_overrides()
    if value is None:
        overrides.pop(key, None)
    else:
        overrides[key] = value


def effective_settings() -> Settings:
    """Configured settings with any in-app override applied."""
    base = get_settings()
    overrides = settings_overrides()
    return replace(base, **overrides) if overrides else base


@st.cache_resource(show_spinner=False)
def _cached_client(_settings: Settings, cache_key: str) -> AuditAgentClient:
    # `_settings` is excluded from the cache key by Streamlit's underscore
    # convention; `cache_key` carries the fields that actually matter.
    return build_client(_settings)


def get_client(settings: Settings | None = None) -> AuditAgentClient:
    settings = settings or effective_settings()
    cache_key = "|".join(
        [
            settings.backend_mode,
            settings.base_url,
            settings.stage_path,
            settings.auth_scheme,
            "token" if settings.token else "no-token",
            str(settings.timeout_s),
            str(settings.verify_ssl),
        ]
    )
    return _cached_client(settings, cache_key)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_health(cache_key: str) -> tuple[bool, str, float | None, str | None]:
    report = get_client().health()
    return report.ok, report.detail, report.latency_ms, report.version


def check_health(*, force: bool = False) -> HealthReport:
    """Backend reachability, cached briefly so the sidebar is not a load test."""
    settings = effective_settings()
    cache_key = f"{settings.backend_mode}|{settings.base_url}"
    if force:
        _cached_health.clear()
    ok, detail, latency, version = _cached_health(cache_key)
    return HealthReport(ok=ok, detail=detail, latency_ms=latency, version=version)


# ---------------------------------------------------------------------------
# Mission session
# ---------------------------------------------------------------------------


def get_session() -> MissionSession | None:
    return st.session_state.get(_SESSION)


def require_session() -> MissionSession:
    session = get_session()
    if session is None:  # pragma: no cover - guarded by the caller
        raise RuntimeError("No mission session is open")
    return session


def start_session(mission_id: str) -> MissionSession:
    settings = effective_settings()
    session = MissionSession(
        mission_id=mission_id.strip(),
        analyst=settings.analyst,
        backend_mode="mock" if settings.is_mock else "live",
    )
    session.record(
        "session_started",
        detail=f"mission {session.mission_id} · backend {session.backend_mode}",
    )
    st.session_state[_SESSION] = session
    st.session_state[_ACTIVE] = STAGE_KEYS[0]
    st.session_state[_VIEW] = "stage"
    _clear_widget_state()
    return session


def close_session() -> None:
    st.session_state.pop(_SESSION, None)
    st.session_state.pop(_ACTIVE, None)
    st.session_state[_VIEW] = "stage"
    _clear_widget_state()


def _clear_widget_state() -> None:
    """Drop per-stage widget values so a new mission starts from a clean form."""
    for key in [k for k in st.session_state if isinstance(k, str) and k.startswith("hitl_")]:
        del st.session_state[key]


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


def active_stage_key() -> str:
    return st.session_state.get(_ACTIVE, STAGE_KEYS[0])


def set_active_stage(key: str) -> None:
    st.session_state[_ACTIVE] = key
    st.session_state[_VIEW] = "stage"


def current_view() -> str:
    return st.session_state.get(_VIEW, "stage")


def set_view(view: str) -> None:
    st.session_state[_VIEW] = view
