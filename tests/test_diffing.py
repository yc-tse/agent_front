"""Change detection.

Regression guard for a real bug: the editors rebuild a full payload on every
render, so a naive `before != after` flagged "unsaved changes" the moment a
stage loaded — which trains analysts to ignore the warning that matters.
"""

from __future__ import annotations

from audit_front.diffing import canonical, change_summary, changed_fields, has_changes
from audit_front.example_backend import AYVENS_UK, ExampleDataAPI
from audit_front.pipeline import get_stage

SCOPE = get_stage("scope_understanding")
METADATA = get_stage("mission_metadata")
RECS = get_stage("historical_recommendations")


class TestNoFalsePositives:
    def test_editors_filling_absent_keys_with_empties_is_not_a_change(self):
        payload = {"entity_filter": ["A", "B"], "primary_scope_driver": "Entity-driven"}
        # What the stage view rebuilds: every list field present, most empty.
        draft = {
            **payload,
            "country_filter": [],
            "risk_filter": [],
            "activity_filter": [],
            "business_line_filter": [],
            "missing_dimensions": [],
            "reasoning": [],
            "brief_scope": "",
        }
        assert has_changes(SCOPE, payload, draft) is False

    def test_a_freshly_loaded_backend_payload_reports_no_change(self):
        client = ExampleDataAPI(latency=False)
        payload = client.run_stage(SCOPE, AYVENS_UK, {}).payload
        draft = {
            **payload,
            "country_filter": [],
            "activity_filter": [],
            "business_line_filter": [],
            "risk_filter": [],
        }
        assert has_changes(SCOPE, payload, draft) is False

    def test_a_renamed_backend_key_is_not_an_analyst_edit(self):
        # Backend spells it `id`; the model calls it `rec_id`.
        payload = {"recommendations": [{"id": "REC-1", "title": "X"}]}
        draft = {"recommendations": [{"rec_id": "REC-1", "title": "X"}]}
        assert has_changes(RECS, payload, draft) is False

    def test_identical_payloads_report_no_change(self):
        payload = {"entities": ["A"], "mission_id": "M"}
        assert has_changes(METADATA, payload, dict(payload)) is False


class TestRealChanges:
    def test_removing_an_entity_is_a_change(self):
        before = {"entity_filter": ["A", "B", "C"]}
        after = {"entity_filter": ["A"]}
        assert has_changes(SCOPE, before, after) is True
        assert changed_fields(SCOPE, before, after) == ["entity_filter"]

    def test_adding_a_value_to_an_empty_field_is_a_change(self):
        before = {"entity_filter": ["A"]}
        after = {"entity_filter": ["A"], "missing_dimensions": ["time period unclear"]}
        assert has_changes(SCOPE, before, after) is True

    def test_changing_a_scalar_is_a_change(self):
        before = {"primary_scope_driver": "Entity-driven"}
        after = {"primary_scope_driver": "Process-driven"}
        assert changed_fields(SCOPE, before, after) == ["primary_scope_driver"]

    def test_reordering_a_list_counts_as_a_change(self):
        before = {"reasoning": ["one", "two"]}
        after = {"reasoning": ["two", "one"]}
        assert has_changes(SCOPE, before, after) is True


class TestSummary:
    def test_summary_counts_removals(self):
        summary = change_summary(
            SCOPE, {"entity_filter": ["A", "B", "C"]}, {"entity_filter": ["A"]}
        )
        assert "entity_filter (-2)" in summary

    def test_summary_counts_additions(self):
        summary = change_summary(SCOPE, {"reasoning": ["a"]}, {"reasoning": ["a", "b"]})
        assert "reasoning (+1)" in summary

    def test_same_length_but_different_content_is_reworded(self):
        summary = change_summary(SCOPE, {"reasoning": ["a"]}, {"reasoning": ["b"]})
        assert "reasoning (reworded)" in summary

    def test_no_change_says_so(self):
        assert change_summary(SCOPE, {"entity_filter": ["A"]}, {"entity_filter": ["A"]}) == (
            "no effective change"
        )

    def test_long_change_lists_are_truncated(self):
        before = {
            "entity_filter": ["A"],
            "risk_filter": ["R"],
            "activity_filter": ["X"],
            "country_filter": ["UK"],
            "reasoning": ["r"],
            "missing_dimensions": ["m"],
        }
        after = {key: [f"{value[0]}-new"] for key, value in before.items()}
        summary = change_summary(SCOPE, before, after)
        assert "and 2 more" in summary


class TestCanonical:
    def test_unparseable_payload_falls_back_to_the_raw_dict(self):
        # An int where a list of axes belongs: the model cannot make sense of
        # it, so canonicalisation gets out of the way instead of raising.
        payload = {"thematic_axes": 12}
        assert canonical(get_stage("briefing"), payload) == payload

    def test_odd_values_are_coerced_rather_than_lost(self):
        # The models are deliberately tolerant, so this parses rather than fails.
        result = canonical(SCOPE, {"entity_filter": ["A", 42]})
        assert result["entity_filter"] == ["A", "42"]

    def test_none_values_are_dropped(self):
        assert "scope_coverage" not in canonical(SCOPE, {"scope_coverage": None})
