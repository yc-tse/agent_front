"""Session semantics: AI vs analyst payloads, approval gating, staleness."""

from __future__ import annotations

from audit_front.pipeline import STAGE_KEYS, downstream_of, get_stage, next_stage
from audit_front.state import MissionSession, StageStatus


def _session() -> MissionSession:
    return MissionSession(mission_id="26-IRB/AYVENS-019", analyst="tester")


class TestPipelineShape:
    def test_stages_are_ordered_and_unique(self):
        assert len(set(STAGE_KEYS)) == len(STAGE_KEYS)
        assert STAGE_KEYS[0] == "mission_metadata"
        assert STAGE_KEYS[-1] == "briefing"

    def test_orders_are_contiguous_and_match_position(self):
        assert [get_stage(k).order for k in STAGE_KEYS] == list(range(len(STAGE_KEYS)))

    def test_dependencies_only_point_backwards(self):
        for key in STAGE_KEYS:
            spec = get_stage(key)
            for dep in spec.depends_on:
                assert get_stage(dep).order < spec.order

    def test_next_stage_ends_at_none(self):
        assert next_stage("mission_metadata").key == "scope_understanding"
        assert next_stage("briefing") is None

    def test_scope_change_invalidates_everything_after_it(self):
        affected = {s.key for s in downstream_of("scope_understanding")}
        assert affected == {
            "risk_events",
            "methodology",
            "historical_reports",
            "historical_recommendations",
            "briefing",
        }

    def test_briefing_has_no_dependants(self):
        assert downstream_of("briefing") == ()


class TestApprovalGating:
    def test_first_stage_runs_immediately(self):
        session = _session()
        assert session.blocking_reason(get_stage("mission_metadata")) is None

    def test_later_stage_is_blocked_until_upstream_is_approved(self):
        session = _session()
        scope = get_stage("scope_understanding")
        assert session.blocking_reason(scope) is not None

        session.complete_run("mission_metadata", {"entities": ["A"]})
        # A produced-but-unapproved stage still blocks.
        assert session.blocking_reason(scope) is not None

        session.approve("mission_metadata")
        assert session.blocking_reason(scope) is None

    def test_next_runnable_walks_the_pipeline(self):
        session = _session()
        assert session.next_runnable().key == "mission_metadata"
        session.complete_run("mission_metadata", {})
        session.approve("mission_metadata")
        assert session.next_runnable().key == "scope_understanding"

    def test_next_actionable_prefers_a_pending_review(self):
        session = _session()
        session.complete_run("mission_metadata", {})
        assert session.next_actionable().key == "mission_metadata"


class TestAnalystOverrides:
    def test_edit_does_not_destroy_the_agent_output(self):
        session = _session()
        session.complete_run("mission_metadata", {"entities": ["A", "B"]})
        session.apply_edit("mission_metadata", {"entities": ["A"]})

        run = session.stage("mission_metadata")
        assert run.ai_payload == {"entities": ["A", "B"]}
        assert run.analyst_payload == {"entities": ["A"]}
        assert run.payload == {"entities": ["A"]}  # the analyst's version flows on
        assert run.edited is True

    def test_revert_restores_the_agent_output(self):
        session = _session()
        session.complete_run("mission_metadata", {"entities": ["A", "B"]})
        session.apply_edit("mission_metadata", {"entities": ["A"]})
        session.revert_edit("mission_metadata")

        run = session.stage("mission_metadata")
        assert run.edited is False
        assert run.payload == {"entities": ["A", "B"]}

    def test_a_fresh_agent_run_supersedes_edits(self):
        session = _session()
        session.complete_run("mission_metadata", {"entities": ["A"]})
        session.apply_edit("mission_metadata", {"entities": ["EDITED"]})
        session.complete_run("mission_metadata", {"entities": ["B"]})

        run = session.stage("mission_metadata")
        assert run.edited is False
        assert run.payload == {"entities": ["B"]}
        assert run.run_count == 2

    def test_context_passes_the_analyst_version_downstream(self):
        session = _session()
        session.complete_run("mission_metadata", {"entities": ["A", "B"]})
        session.apply_edit("mission_metadata", {"entities": ["A"]})
        session.approve("mission_metadata")

        context = session.context_for(get_stage("scope_understanding"))
        assert context["mission_metadata"] == {"entities": ["A"]}


class TestStaleness:
    def test_editing_upstream_marks_downstream_stale(self):
        session = _session()
        for key in ("mission_metadata", "scope_understanding", "risk_events"):
            session.complete_run(key, {"x": 1})
            session.approve(key)

        session.apply_edit("scope_understanding", {"entity_filter": ["A"]})
        assert session.stage("risk_events").stale is True
        assert session.stage("mission_metadata").stale is False

    def test_stages_without_results_are_not_marked_stale(self):
        session = _session()
        session.complete_run("mission_metadata", {})
        session.apply_edit("mission_metadata", {"entities": []})
        assert session.stale_stages == []

    def test_re_running_clears_staleness(self):
        session = _session()
        session.complete_run("scope_understanding", {})
        session.complete_run("risk_events", {})
        session.apply_edit("scope_understanding", {"entity_filter": ["A"]})
        assert session.stage("risk_events").stale is True

        session.complete_run("risk_events", {"events": []})
        assert session.stage("risk_events").stale is False

    def test_editing_an_approved_stage_reopens_it(self):
        session = _session()
        session.complete_run("mission_metadata", {})
        session.approve("mission_metadata")
        session.apply_edit("mission_metadata", {"entities": ["A"]})
        assert session.stage("mission_metadata").status is StageStatus.REVIEW


class TestAuditTrail:
    def test_every_transition_is_recorded(self):
        session = _session()
        session.start_run("mission_metadata")
        session.complete_run("mission_metadata", {"entities": ["A"]})
        session.apply_edit("mission_metadata", {"entities": []})
        session.approve("mission_metadata", note="entity list was stale")

        actions = [event.action for event in session.audit_trail]
        assert actions == [
            "stage_run_started",
            "stage_completed",
            "stage_edited",
            "stage_approved",
        ]

    def test_agent_and_analyst_are_distinguishable(self):
        session = _session()
        session.complete_run("mission_metadata", {})
        session.approve("mission_metadata")
        actors = {event.actor for event in session.audit_trail}
        assert actors == {"agent", "tester"}

    def test_approval_note_reaches_the_trail(self):
        session = _session()
        session.complete_run("mission_metadata", {})
        session.approve("mission_metadata", note="checked against the plan")
        assert "checked against the plan" in session.audit_trail[-1].detail

    def test_failure_is_recorded_with_its_message(self):
        session = _session()
        session.start_run("mission_metadata")
        session.fail_run("mission_metadata", "HTTP 503")
        run = session.stage("mission_metadata")
        assert run.status is StageStatus.ERROR
        assert run.error == "HTTP 503"
        assert session.audit_trail[-1].action == "stage_failed"


class TestSerialisation:
    def test_export_dict_keeps_both_payloads(self):
        session = _session()
        session.complete_run("mission_metadata", {"entities": ["A", "B"]})
        session.apply_edit("mission_metadata", {"entities": ["A"]})

        payload = session.to_dict()["stages"]["mission_metadata"]
        assert payload["ai_payload"] == {"entities": ["A", "B"]}
        assert payload["analyst_payload"] == {"entities": ["A"]}
        assert payload["edited_by_analyst"] is True
