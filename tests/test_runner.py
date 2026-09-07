"""End-to-end pipeline behaviour against the mock backend.

The central claim under test: an analyst edit in stage 2 really does change
stages 3 to 6. If that ever stops holding, the human-in-the-loop story is
decoration.
"""

from __future__ import annotations

import pytest

from audit_front.client import BackendError, StageResponse
from audit_front.mock_backend import AYVENS_DE, AYVENS_UK, MockAuditAgentClient
from audit_front.pipeline import STAGE_KEYS, get_stage
from audit_front.runner import run_draft_pipeline, run_stage
from audit_front.state import MissionSession, StageStatus


@pytest.fixture
def client() -> MockAuditAgentClient:
    return MockAuditAgentClient(latency=False)


def _session(mission_id: str = AYVENS_UK) -> MissionSession:
    return MissionSession(mission_id=mission_id, analyst="tester")


def _advance(session: MissionSession, client, upto: str) -> None:
    """Run and approve every stage up to and including ``upto``."""
    for key in STAGE_KEYS:
        run_stage(session, client, get_stage(key))
        session.approve(key)
        if key == upto:
            return


class TestSingleStage:
    def test_running_a_stage_leaves_it_awaiting_review(self, client):
        session = _session()
        run_stage(session, client, get_stage("mission_metadata"))
        run = session.stage("mission_metadata")
        assert run.status is StageStatus.REVIEW
        assert run.parsed().mission_id == AYVENS_UK
        assert len(run.parsed().entities) == 8

    def test_trace_id_is_captured(self, client):
        session = _session()
        run_stage(session, client, get_stage("mission_metadata"))
        assert session.stage("mission_metadata").trace_id is not None

    def test_an_unknown_mission_fails_without_raising(self, client):
        session = _session("99-XXX/NOPE-001")
        run = run_stage(session, client, get_stage("mission_metadata"))
        assert run.status is StageStatus.ERROR
        assert "not one of the bundled samples" in run.error

    def test_an_unexpected_client_error_is_contained(self):
        class Exploding:
            label = "broken"

            def run_stage(self, *args, **kwargs):
                raise ValueError("kaboom")

        session = _session()
        run = run_stage(session, Exploding(), get_stage("mission_metadata"))
        assert run.status is StageStatus.ERROR
        assert "kaboom" in run.error

    def test_feedback_reaches_the_backend_and_the_trail(self, client):
        session = _session()
        run_stage(session, client, get_stage("mission_metadata"))
        session.approve("mission_metadata")
        run_stage(
            session, client, get_stage("scope_understanding"), feedback="treat as process-driven"
        )
        reasoning = session.stage("scope_understanding").parsed().reasoning
        assert any("treat as process-driven" in line for line in reasoning)
        assert any(e.action == "rerun_requested" for e in session.audit_trail)


class TestScopePropagation:
    def test_narrowing_the_scope_narrows_the_loss_events(self, client):
        session = _session(AYVENS_DE)
        _advance(session, client, "mission_metadata")

        run_stage(session, client, get_stage("scope_understanding"))
        full = session.stage("scope_understanding").parsed()
        assert len(full.entity_filter) == 3

        session.apply_edit(
            "scope_understanding",
            {
                **session.stage("scope_understanding").payload,
                "entity_filter": ["ALD AUTOMOTIVE GMBH"],
            },
        )
        session.approve("scope_understanding")

        run_stage(session, client, get_stage("risk_events"))
        events = session.stage("risk_events").parsed().events
        assert {e.entity for e in events} == {"ALD AUTOMOTIVE GMBH"}
        assert len(events) == 1

    def test_narrowing_the_scope_narrows_the_recommendations(self, client):
        session = _session(AYVENS_DE)
        _advance(session, client, "mission_metadata")
        run_stage(session, client, get_stage("scope_understanding"))
        session.apply_edit(
            "scope_understanding",
            {
                **session.stage("scope_understanding").payload,
                "entity_filter": ["AYVENS REMARKETING GMBH"],
            },
        )
        session.approve("scope_understanding")

        run_stage(session, client, get_stage("historical_recommendations"))
        recs = session.stage("historical_recommendations").parsed().recommendations
        assert {r.entity for r in recs} == {"AYVENS REMARKETING GMBH"}

    def test_the_briefing_perimeter_follows_the_validated_scope(self, client):
        session = _session(AYVENS_UK)
        for key in STAGE_KEYS[:-1]:
            run_stage(session, client, get_stage(key))
            if key == "scope_understanding":
                session.apply_edit(
                    "scope_understanding",
                    {
                        **session.stage(key).payload,
                        "entity_filter": ["LEASEPLAN UK LIMITED"],
                    },
                )
            session.approve(key)

        run_stage(session, client, get_stage("briefing"))
        briefing = session.stage("briefing").parsed()
        assert briefing.perimeter == ["LEASEPLAN UK LIMITED"]


class TestSampleMissions:
    """Both bundled samples must survive the whole pipeline.

    Regression guard: the Germany sample once had no `briefing` payload, so
    stage 6 failed. Every earlier test still passed, because none of them
    asserted that a sample mission runs end to end.
    """

    @pytest.mark.parametrize("mission_id", [AYVENS_UK, AYVENS_DE])
    def test_every_sample_completes_all_six_stages(self, client, mission_id):
        session = _session(mission_id)
        for key in STAGE_KEYS:
            run = run_stage(session, client, get_stage(key))
            assert run.status is StageStatus.REVIEW, f"{mission_id} / {key}: {run.error}"
            session.approve(key)
        assert session.is_complete

    @pytest.mark.parametrize("mission_id", [AYVENS_UK, AYVENS_DE])
    def test_every_sample_produces_a_usable_briefing(self, client, mission_id):
        session = _session(mission_id)
        for key in STAGE_KEYS:
            run_stage(session, client, get_stage(key))
            session.approve(key)

        briefing = session.stage("briefing").parsed()
        assert briefing.objective
        assert briefing.perimeter
        assert briefing.thematic_axes
        assert briefing.open_questions

    def test_the_two_samples_take_opposite_paths(self, client):
        """One returns three empty result sets; the other returns populated ones."""
        empty = _session(AYVENS_UK)
        full = _session(AYVENS_DE)
        for session in (empty, full):
            for key in STAGE_KEYS:
                run_stage(session, client, get_stage(key))
                session.approve(key)

        assert empty.stage("risk_events").parsed().resolved_count == 0
        assert full.stage("risk_events").parsed().resolved_count == 4
        assert empty.stage("methodology").parsed().resolved_found is False
        assert full.stage("methodology").parsed().resolved_found is True
        assert empty.stage("historical_recommendations").parsed().resolved_found is False
        assert full.stage("historical_recommendations").parsed().resolved_found is True


class TestEmptyResultsAreStillResults:
    def test_the_uk_sample_reproduces_its_three_empty_stages(self, client):
        session = _session(AYVENS_UK)
        for key in STAGE_KEYS:
            run_stage(session, client, get_stage(key))
            session.approve(key)

        assert session.stage("risk_events").parsed().resolved_count == 0
        assert session.stage("methodology").parsed().resolved_found is False
        assert session.stage("historical_recommendations").parsed().resolved_found is False
        # …and each still explains itself.
        assert session.stage("risk_events").parsed().interpretation
        assert session.stage("methodology").parsed().recommended_approach
        assert session.stage("historical_recommendations").parsed().implications


class TestDraftRun:
    def test_draft_run_produces_every_stage_without_approving_any(self, client):
        session = _session()
        completed = run_draft_pipeline(session, client)
        assert completed == list(STAGE_KEYS)
        assert session.approved_count == 0
        assert all(
            session.stage(key).status is StageStatus.REVIEW for key in STAGE_KEYS
        )

    def test_draft_run_is_recorded_as_unattended(self, client):
        session = _session()
        run_draft_pipeline(session, client)
        actions = [e.action for e in session.audit_trail]
        assert "draft_run_started" in actions
        assert "draft_run_finished" in actions

    def test_draft_run_stops_at_the_first_failure(self):
        class FailsAtScope(MockAuditAgentClient):
            def run_stage(self, stage, mission_id, context, **kwargs):
                if stage.key == "scope_understanding":
                    raise BackendError("backend down", status_code=503)
                return super().run_stage(stage, mission_id, context, **kwargs)

        session = _session()
        completed = run_draft_pipeline(session, FailsAtScope(latency=False))
        assert completed == ["mission_metadata"]
        assert session.stage("scope_understanding").status is StageStatus.ERROR
        assert session.stage("risk_events").status is StageStatus.PENDING

    def test_draft_run_does_not_re_run_a_stage_already_awaiting_review(self, client):
        session = _session()
        run_stage(session, client, get_stage("mission_metadata"))
        first_trace = session.stage("mission_metadata").trace_id

        run_draft_pipeline(session, client)
        assert session.stage("mission_metadata").trace_id == first_trace
        assert session.stage("mission_metadata").run_count == 1


class TestMockContract:
    def test_the_mock_returns_the_same_shape_as_the_http_client(self, client):
        response = client.run_stage(get_stage("mission_metadata"), AYVENS_UK, {})
        assert isinstance(response, StageResponse)
        assert isinstance(response.payload, dict)
        assert isinstance(response.warnings, list)

    def test_health_reports_ok(self, client):
        assert client.health().ok is True
