"""Render every view of the real app and assert it does not raise.

Streamlit's own `AppTest` runs `app.py` without a browser, so this catches the
class of bug that unit tests miss entirely — an invalid icon, a bad column
spec, a widget key collision, a stage renderer that assumes a field exists.
Both sample missions are exercised because they take opposite paths: one
returns three empty result sets, the other returns populated ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from audit_front.config import get_settings
from audit_front.mock_backend import AYVENS_DE, AYVENS_UK, MockAuditAgentClient
from audit_front.pipeline import STAGE_KEYS, get_stage
from audit_front.runner import run_stage
from audit_front.state import MissionSession

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def mock_backend(monkeypatch):
    monkeypatch.setenv("AUDIT_BACKEND_MODE", "mock")
    monkeypatch.setenv("AUDIT_API_BASE_URL", "")
    monkeypatch.setenv("AUDIT_ANALYST", "tester")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _completed_session(mission_id: str, *, approve: bool = True) -> MissionSession:
    session = MissionSession(mission_id=mission_id, analyst="tester")
    client = MockAuditAgentClient(latency=False)
    for key in STAGE_KEYS:
        run = run_stage(session, client, get_stage(key))
        # Fail loudly here rather than quietly rendering an error state, which
        # would make every view test pass while a sample mission was broken.
        assert run.error is None, f"{mission_id} / {key}: {run.error}"
        if approve:
            session.approve(key)
    return session


def _app(session: MissionSession | None = None, *, stage: str | None = None, view: str = "stage"):
    at = AppTest.from_file(str(APP), default_timeout=60)
    if session is not None:
        at.session_state["af_session"] = session
        at.session_state["af_active_stage"] = stage or STAGE_KEYS[0]
        at.session_state["af_view"] = view
    at.run()
    return at


def _assert_clean(at, context: str) -> None:
    assert not at.exception, f"{context} raised: {[str(e) for e in at.exception]}"


class TestLanding:
    def test_landing_page_renders(self):
        at = _app()
        _assert_clean(at, "landing page")
        assert any("Pre-mission preparation" in md.value for md in at.markdown)

    def test_sample_missions_are_offered_in_mock_mode(self):
        at = _app()
        labels = [button.label for button in at.sidebar.button]
        assert AYVENS_UK in labels
        assert AYVENS_DE in labels


class TestStageRendering:
    @pytest.mark.parametrize("mission_id", [AYVENS_UK, AYVENS_DE])
    @pytest.mark.parametrize("stage_key", STAGE_KEYS)
    def test_every_stage_renders_for_both_samples(self, mission_id, stage_key):
        session = _completed_session(mission_id)
        at = _app(session, stage=stage_key)
        _assert_clean(at, f"{mission_id} / {stage_key}")

    @pytest.mark.parametrize("stage_key", STAGE_KEYS)
    def test_stages_render_before_they_are_approved(self, stage_key):
        session = _completed_session(AYVENS_UK, approve=False)
        at = _app(session, stage=stage_key)
        _assert_clean(at, f"unapproved {stage_key}")

    def test_a_never_run_stage_offers_a_run_button(self):
        session = MissionSession(mission_id=AYVENS_UK, analyst="tester")
        at = _app(session, stage="mission_metadata")
        _assert_clean(at, "pending stage")
        assert any("Run mission metadata" in button.label for button in at.button)

    def test_a_blocked_stage_explains_what_to_approve_first(self):
        session = MissionSession(mission_id=AYVENS_UK, analyst="tester")
        at = _app(session, stage="briefing")
        _assert_clean(at, "blocked stage")
        assert any("Approve" in info.value for info in at.info)

    def test_a_failed_stage_shows_the_error_and_a_retry(self):
        session = MissionSession(mission_id=AYVENS_UK, analyst="tester")
        session.start_run("mission_metadata")
        session.fail_run("mission_metadata", "Could not reach the backend · HTTP 503")
        at = _app(session, stage="mission_metadata")
        _assert_clean(at, "failed stage")
        assert any("HTTP 503" in error.value for error in at.error)
        assert any(button.label == "Try again" for button in at.button)


class TestReviewState:
    def test_a_freshly_loaded_stage_reports_no_unsaved_changes(self):
        # Regression: the editors rebuild the payload each render, which used
        # to look like an analyst edit before anyone touched anything.
        for stage_key in STAGE_KEYS:
            session = _completed_session(AYVENS_DE, approve=False)
            at = _app(session, stage=stage_key)
            _assert_clean(at, f"unsaved-changes check on {stage_key}")
            assert not any("unsaved changes" in info.value for info in at.info), (
                f"{stage_key} claimed unsaved changes on first render"
            )

    def test_an_edited_stage_marks_its_dependants_stale(self):
        session = _completed_session(AYVENS_UK)
        session.apply_edit(
            "scope_understanding",
            {**session.stage("scope_understanding").payload, "entity_filter": ["ONE ENTITY"]},
        )
        at = _app(session, stage="risk_events")
        _assert_clean(at, "stale stage")
        assert any("upstream stage changed" in warning.value for warning in at.warning)

    def test_an_empty_scope_is_flagged_as_an_error(self):
        session = _completed_session(AYVENS_UK, approve=False)
        session.apply_edit("scope_understanding", {"primary_scope_driver": "Entity-driven"})
        at = _app(session, stage="scope_understanding")
        _assert_clean(at, "empty scope")
        assert any("No filter dimension is set" in error.value for error in at.error)


class TestOutputViews:
    @pytest.mark.parametrize("mission_id", [AYVENS_UK, AYVENS_DE])
    def test_briefing_pack_renders(self, mission_id):
        at = _app(_completed_session(mission_id), view="briefing_pack")
        _assert_clean(at, f"briefing pack for {mission_id}")
        assert any("Briefing pack" in md.value for md in at.markdown)

    def test_briefing_pack_warns_when_stages_are_unapproved(self):
        at = _app(_completed_session(AYVENS_UK, approve=False), view="briefing_pack")
        _assert_clean(at, "incomplete briefing pack")
        assert any("Not every stage is approved" in w.value for w in at.warning)

    def test_audit_trail_renders(self):
        at = _app(_completed_session(AYVENS_UK), view="audit_trail")
        _assert_clean(at, "audit trail")
        assert any("Audit trail" in md.value for md in at.markdown)

    def test_audit_trail_is_empty_but_valid_on_a_new_session(self):
        session = MissionSession(mission_id=AYVENS_UK, analyst="tester")
        at = _app(session, view="audit_trail")
        _assert_clean(at, "empty audit trail")


class TestMalformedPayloads:
    """The backend may drift; the UI must degrade rather than break."""

    @pytest.mark.parametrize("stage_key", STAGE_KEYS)
    def test_an_empty_payload_still_renders(self, stage_key):
        session = MissionSession(mission_id=AYVENS_UK, analyst="tester")
        for key in STAGE_KEYS:
            session.complete_run(key, {})
            session.approve(key)
        at = _app(session, stage=stage_key)
        _assert_clean(at, f"empty payload on {stage_key}")

    @pytest.mark.parametrize("stage_key", STAGE_KEYS)
    def test_an_unrecognised_payload_still_renders(self, stage_key):
        session = MissionSession(mission_id=AYVENS_UK, analyst="tester")
        for key in STAGE_KEYS:
            session.complete_run(key, {"totally": "unexpected", "shape": [1, 2, 3]})
            session.approve(key)
        at = _app(session, stage=stage_key)
        _assert_clean(at, f"unrecognised payload on {stage_key}")
