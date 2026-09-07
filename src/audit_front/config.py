"""Runtime configuration.

Values are resolved in this order: Streamlit secrets -> process env -> `.env`
-> built-in default. That order lets the same code run on a laptop (`.env`),
in a container (env vars) and on a Streamlit deployment (secrets) without
changes.
"""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass, field
from functools import lru_cache

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv absent or unreadable .env
    pass


def _secret(name: str) -> str | None:
    """Read from Streamlit secrets without importing streamlit at module load."""
    try:
        import streamlit as st

        # Accessing st.secrets raises if no secrets file exists at all.
        return str(st.secrets[name]) if name in st.secrets else None
    except Exception:
        return None


def _get(name: str, default: str = "") -> str:
    value = _secret(name)
    if value is None:
        value = os.getenv(name)
    return default if value is None or value == "" else value


def _get_bool(name: str, default: bool) -> bool:
    return _get(name, "true" if default else "false").strip().lower() in {"1", "true", "yes", "on"}


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)))
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(float(_get(name, str(default))))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Everything the front-end needs to know about its backend."""

    backend_mode: str = "mock"  # "mock" | "live"
    base_url: str = ""
    stage_path: str = "/api/v1/missions/{mission_id}/stages/{stage}"
    health_path: str = "/health"
    job_path: str = "/api/v1/jobs/{job_id}"
    auth_scheme: str = "none"  # "none" | "bearer" | "api_key"
    token: str = ""
    api_key_header: str = "X-API-Key"
    timeout_s: float = 120.0
    max_retries: int = 2
    poll_interval_s: float = 2.0
    verify_ssl: bool = True
    analyst: str = "unknown"
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def is_mock(self) -> bool:
        return self.backend_mode == "mock" or not self.base_url

    def auth_headers(self) -> dict[str, str]:
        headers = dict(self.extra_headers)
        if self.auth_scheme == "bearer" and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        elif self.auth_scheme == "api_key" and self.token:
            headers[self.api_key_header] = self.token
        return headers

    def url_for(self, path_template: str, **params: str) -> str:
        return self.base_url.rstrip("/") + path_template.format(**params)

    def redacted(self) -> dict[str, object]:
        """Config snapshot safe to display in the UI / write to an export."""
        return {
            "backend_mode": "mock" if self.is_mock else "live",
            "base_url": self.base_url or "(none)",
            "stage_path": self.stage_path,
            "auth_scheme": self.auth_scheme,
            "token": "***set***" if self.token else "(unset)",
            "timeout_s": self.timeout_s,
            "max_retries": self.max_retries,
            "verify_ssl": self.verify_ssl,
            "analyst": self.analyst,
        }


def _default_analyst() -> str:
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover - no OS user (container)
        return "unknown"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    base_url = _get("AUDIT_API_BASE_URL").rstrip("/")
    mode = _get("AUDIT_BACKEND_MODE", "mock").strip().lower()
    if mode not in {"mock", "live"}:
        mode = "mock"
    return Settings(
        backend_mode=mode,
        base_url=base_url,
        stage_path=_get("AUDIT_API_STAGE_PATH", "/api/v1/missions/{mission_id}/stages/{stage}"),
        health_path=_get("AUDIT_API_HEALTH_PATH", "/health"),
        job_path=_get("AUDIT_API_JOB_PATH", "/api/v1/jobs/{job_id}"),
        auth_scheme=_get("AUDIT_API_AUTH_SCHEME", "none").strip().lower(),
        token=_get("AUDIT_API_TOKEN"),
        api_key_header=_get("AUDIT_API_KEY_HEADER", "X-API-Key"),
        timeout_s=_get_float("AUDIT_API_TIMEOUT_S", 120.0),
        max_retries=_get_int("AUDIT_API_MAX_RETRIES", 2),
        poll_interval_s=_get_float("AUDIT_API_POLL_INTERVAL_S", 2.0),
        verify_ssl=_get_bool("AUDIT_API_VERIFY_SSL", True),
        analyst=_get("AUDIT_ANALYST", _default_analyst()),
    )
