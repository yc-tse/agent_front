"""The export is the deliverable — and the record of who decided what."""

from __future__ import annotations

import json

from audit_front.example_backend import AYVENS_DE, AYVENS_UK, ExampleDataAPI
from audit_front.exporters import (
    export_filename,
    session_to_json,
    session_to_markdown,
    stage_markdown,
)
from audit_front.pipeline import STAGE_KEYS, get_stage
from audit_front.runner import run_stage
from audit_front.state import MissionSession


def _completed_session(mission_id: str = AYVENS_UK) -> MissionSession:
    session = MissionSession(mission_id=mission_id, analyst="tester")
    client = ExampleDataAPI(latency=False)
    for key in STAGE_KEYS:
        run_stage(session, client, get_stage(key))
        session.approve(key)
    return session


class TestMarkdown:
    def test_all_six_sections_are_present(self):
        markdown = session_to_markdown(_completed_session())
        for spec_key in STAGE_KEYS:
            assert f"## {get_stage(spec_key).title}" in markdown

    def test_header_names_the_mission_and_the_analyst(self):
        markdown = session_to_markdown(_completed_session())
        assert AYVENS_UK in markdown
        assert "tester" in markdown

    def test_briefing_only_export_omits_the_other_stages(self):
        markdown = session_to_markdown(_completed_session(), include_all_stages=False)
        assert "## 6. Consolidated pre-mission briefing" in markdown
        assert "## 3. Operational risk events in scope" not in markdown

    def test_briefing_only_banners_do_not_name_excluded_stages(self):
        markdown = session_to_markdown(_completed_session(), include_all_stages=False)
        banner = markdown.split("---", 1)[0]
        assert "3. Operational risk events in scope" not in banner

    def test_empty_stages_state_their_result_rather_than_nothing(self):
        session = _completed_session(AYVENS_UK)
        risk_md = stage_markdown(session.stage("risk_events"))
        assert "none surfaced" in risk_md
        method_md = stage_markdown(session.stage("methodology"))
        assert "No Methodo found" in method_md

    def test_loss_events_render_as_a_table(self):
        session = _completed_session(AYVENS_DE)
        markdown = stage_markdown(session.stage("risk_events"))
        assert "| Ref | Date | Entity |" in markdown
        assert "OPL-2024-3312" in markdown

    def test_a_stage_never_run_says_so(self):
        session = MissionSession(mission_id="M")
        assert stage_markdown(session.stage("briefing")) == "_Stage not run._"

    def test_provenance_section_counts_analyst_edits(self):
        session = _completed_session()
        session.apply_edit(
            "scope_understanding",
            {**session.stage("scope_understanding").payload, "entity_filter": ["ONE"]},
        )
        markdown = session_to_markdown(session)
        assert "## Provenance" in markdown
        assert "Stages amended by the analyst: 1" in markdown

    def test_stale_stages_are_flagged_at_the_top(self):
        session = _completed_session()
        session.apply_edit(
            "scope_understanding",
            {**session.stage("scope_understanding").payload, "entity_filter": ["ONE"]},
        )
        markdown = session_to_markdown(session)
        assert "Stale stages at export time" in markdown

    def test_example_data_stages_are_flagged_on_the_first_page(self):
        # A pack that mixes live and example data is otherwise indistinguishable
        # from a fully live one — which is how example figures end up quoted.
        markdown = session_to_markdown(_completed_session())
        assert "Not from the live backend" in markdown
        assert "must not be relied on as findings" in markdown

    def test_a_partly_live_pack_names_only_the_example_sections(self):
        session = _completed_session()
        for key in STAGE_KEYS:
            session.stage(key).source = "live"
        session.stage("methodology").source = "example"
        banner = session_to_markdown(session).split("---", 1)[0]
        assert "4. Methodology references" in banner
        assert "1. Mission metadata" not in banner
        assert "Every section" not in banner

    def test_a_fully_live_pack_carries_no_example_banner(self):
        session = _completed_session()
        for key in STAGE_KEYS:
            session.stage(key).source = "live"
        markdown = session_to_markdown(session)
        assert "Not from the live backend" not in markdown

    def test_each_stage_states_which_backend_answered(self):
        session = _completed_session()
        session.stage("risk_events").source = "live"
        markdown = session_to_markdown(session)
        assert "live backend" in markdown
        assert "example data" in markdown

    def test_the_source_is_recorded_per_stage_in_the_json(self):
        document = json.loads(session_to_json(_completed_session()))
        assert document["stages"]["risk_events"]["source"] == "example"

    def test_pipe_characters_in_details_do_not_break_the_table(self):
        session = _completed_session()
        session.record("note", stage="briefing", detail="a | b | c")
        markdown = session_to_markdown(session)
        assert r"a \| b \| c" in markdown


class TestJson:
    def test_record_is_valid_json_with_both_payloads(self):
        session = _completed_session()
        session.apply_edit(
            "mission_metadata",
            {**session.stage("mission_metadata").payload, "entities": ["ONLY ONE"]},
        )
        document = json.loads(session_to_json(session))

        stage = document["stages"]["mission_metadata"]
        assert len(stage["ai_payload"]["entities"]) == 8
        assert stage["analyst_payload"]["entities"] == ["ONLY ONE"]
        assert stage["edited_by_analyst"] is True

    def test_audit_trail_is_included_in_order(self):
        document = json.loads(session_to_json(_completed_session()))
        trail = document["audit_trail"]
        assert trail[0]["action"] == "stage_run_started"
        assert any(event["action"] == "stage_approved" for event in trail)

    def test_completion_flags_are_reported(self):
        document = json.loads(session_to_json(_completed_session()))
        assert document["complete"] is True
        assert document["approved_stages"] == 6


class TestFilenames:
    def test_slashes_do_not_leak_into_the_filename(self):
        session = MissionSession(mission_id="26-IRB/AYVENS-019")
        name = export_filename(session, "md")
        assert "/" not in name
        assert name.startswith("premission_26-IRB-AYVENS-019_")
        assert name.endswith(".md")
