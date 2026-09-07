"""Envelope handling — the part most likely to meet a surprise from the backend."""

from __future__ import annotations

from audit_front.client import (
    BackendError,
    build_request_body,
    extract_trace_id,
    extract_warnings,
    unwrap_payload,
)
from audit_front.pipeline import get_stage


class TestUnwrapPayload:
    def test_data_envelope(self):
        assert unwrap_payload({"status": "ok", "data": {"a": 1}}) == {"a": 1}

    def test_result_envelope(self):
        assert unwrap_payload({"result": {"a": 1}}) == {"a": 1}

    def test_bare_payload_passes_through(self):
        assert unwrap_payload({"mission_id": "X", "entities": []}) == {
            "mission_id": "X",
            "entities": [],
        }

    def test_transport_keys_are_stripped_from_a_bare_payload(self):
        payload = unwrap_payload(
            {"mission_id": "X", "status": "completed", "trace_id": "t-1", "warnings": []}
        )
        assert payload == {"mission_id": "X"}

    def test_a_payload_that_is_only_transport_keys_is_not_emptied(self):
        # Better to show something odd than to show nothing at all.
        assert unwrap_payload({"status": "completed"}) == {"status": "completed"}

    def test_string_payload_becomes_markdown(self):
        assert unwrap_payload({"data": "# Briefing"}) == {"markdown": "# Briefing"}

    def test_list_payload_is_wrapped(self):
        assert unwrap_payload([{"a": 1}]) == {"items": [{"a": 1}]}

    def test_none_is_an_empty_payload(self):
        assert unwrap_payload(None) == {}


class TestMetadataExtraction:
    def test_warnings_from_a_list(self):
        assert extract_warnings({"warnings": ["slow", ""]}) == ["slow"]

    def test_warnings_from_a_string(self):
        assert extract_warnings({"warnings": "partial data"}) == ["partial data"]

    def test_trace_id_from_body(self):
        assert extract_trace_id({"traceId": "abc"}) == "abc"

    def test_trace_id_falls_back_to_headers(self):
        assert extract_trace_id({}, {"X-Request-Id": "hdr-1"}) == "hdr-1"

    def test_no_trace_id_is_none(self):
        assert extract_trace_id({}, {}) is None


class TestRequestBody:
    def test_context_and_feedback_are_included(self):
        body = build_request_body(
            get_stage("risk_events"),
            "26-IRB/AYVENS-019",
            {"scope_understanding": {"entity_filter": ["A"]}},
            feedback="narrow to leasing entities",
            analyst="tester",
        )
        assert body["mission_id"] == "26-IRB/AYVENS-019"
        assert body["stage"] == "risk_events"
        assert body["context"]["scope_understanding"]["entity_filter"] == ["A"]
        assert body["analyst_feedback"] == "narrow to leasing entities"
        assert body["requested_by"] == "tester"

    def test_optional_keys_are_omitted_when_unused(self):
        body = build_request_body(get_stage("mission_metadata"), "M", {})
        assert "analyst_feedback" not in body
        assert "overrides" not in body


class TestBackendError:
    def test_message_carries_the_actionable_context(self):
        error = BackendError(
            "Not authorised for this mission",
            status_code=403,
            detail="mission not in your scope",
            trace_id="t-9",
        )
        rendered = str(error)
        assert "Not authorised" in rendered
        assert "HTTP 403" in rendered
        assert "t-9" in rendered
