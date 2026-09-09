"""The integration surface: six named methods, and how they get routed.

These guard the seams a future developer will use to connect the real backend.
If `api_method` on a stage ever stops resolving to a real method, or a router
sends a stage to the wrong implementation, that shows up here rather than as a
mystery in the UI.
"""

from __future__ import annotations

import inspect

import pytest
from sample_missions import AYVENS_UK

from audit_front.api import BackendAPI, StageRequest, StageResponse
from audit_front.client import HttpBackendAPI
from audit_front.config import Settings
from audit_front.example_backend import ExampleDataAPI
from audit_front.pipeline import STAGE_KEYS, STAGES, get_stage
from audit_front.routing import StageRouter, build_backend, resolve_live_stages

API_METHODS = [spec.api_method for spec in STAGES]


class RecordingAPI(BackendAPI):
    """A stand-in that records which named method was called."""

    def __init__(self, label: str = "recording") -> None:
        self.label = label
        self.calls: list[str] = []

    def _record(self, request: StageRequest) -> StageResponse:
        self.calls.append(request.stage_key)
        return StageResponse(payload={"called": request.stage_key, "by": self.label})

    fetch_mission_metadata = _record
    analyse_mission_scope = _record
    fetch_risk_events = _record
    fetch_methodology = _record
    fetch_historical_reports = _record
    fetch_historical_recommendations = _record
    build_briefing = _record


def _settings(**overrides) -> Settings:
    base = {"backend_mode": "live", "base_url": "https://backend.internal"}
    return Settings(**{**base, **overrides})


class TestSurfaceIsComplete:
    """One method per backend API, declared in the stage table."""

    def test_every_stage_declares_a_method(self):
        assert len(API_METHODS) == len(STAGE_KEYS)
        assert len(set(API_METHODS)) == len(STAGE_KEYS), "two stages share a method name"

    def test_recording_double_covers_the_whole_surface(self):
        # Guards the guard: if a stage is added and RecordingAPI is not updated,
        # every dispatch test would fail on instantiation rather than on intent.
        assert RecordingAPI() is not None

    @pytest.mark.parametrize("spec", STAGES, ids=[s.key for s in STAGES])
    def test_the_declared_method_exists_and_is_abstract(self, spec):
        method = getattr(BackendAPI, spec.api_method, None)
        assert method is not None, f"BackendAPI has no {spec.api_method}()"
        assert getattr(method, "__isabstractmethod__", False), (
            f"{spec.api_method}() must stay abstract so implementations cannot silently skip it"
        )

    @pytest.mark.parametrize("implementation", [HttpBackendAPI, ExampleDataAPI, StageRouter])
    @pytest.mark.parametrize("method_name", API_METHODS)
    def test_every_implementation_provides_every_method(self, implementation, method_name):
        method = getattr(implementation, method_name, None)
        assert callable(method), f"{implementation.__name__} is missing {method_name}()"

    @pytest.mark.parametrize("method_name", API_METHODS)
    def test_methods_take_a_stage_request(self, method_name):
        parameters = list(inspect.signature(getattr(BackendAPI, method_name)).parameters)
        assert parameters == ["self", "request"], (
            f"{method_name}() should take a single StageRequest, for a stable signature"
        )

    def test_no_implementation_is_left_abstract(self):
        # Instantiating proves every abstract method is implemented.
        assert ExampleDataAPI(latency=False) is not None
        assert HttpBackendAPI(_settings()) is not None


class TestDispatch:
    def test_run_stage_calls_the_method_named_by_the_stage(self):
        api = RecordingAPI()
        for key in STAGE_KEYS:
            response = api.run_stage(get_stage(key), "26-IRB/X-001", {})
            assert response.payload == {"called": key, "by": "recording"}
        assert api.calls == list(STAGE_KEYS)

    def test_dispatch_builds_the_request_from_its_arguments(self):
        captured: list[StageRequest] = []

        class Capturing(RecordingAPI):
            def fetch_risk_events(self, request: StageRequest) -> StageResponse:
                captured.append(request)
                return StageResponse(payload={})

        Capturing().run_stage(
            get_stage("risk_events"),
            "26-IRB/X-001",
            {"scope_understanding": {"entity_filter": ["A"]}},
            feedback="narrow it",
            analyst="tester",
        )
        request = captured[0]
        assert request.mission_id == "26-IRB/X-001"
        assert request.entity_filter == ["A"]
        assert request.feedback == "narrow it"
        assert request.analyst == "tester"

    def test_the_answering_source_is_stamped_on_the_response(self):
        response = ExampleDataAPI(latency=False).run_stage(
            get_stage("mission_metadata"), AYVENS_UK, {}
        )
        assert response.source == "example"

    def test_an_explicit_source_is_not_overwritten(self):
        class Sourced(RecordingAPI):
            def fetch_mission_metadata(self, request):
                return StageResponse(payload={}, source="live")

        response = Sourced().run_stage(get_stage("mission_metadata"), "M", {})
        assert response.source == "live"


class TestLiveStageResolution:
    def test_mock_mode_puts_every_stage_on_example_data(self):
        assert resolve_live_stages(_settings(backend_mode="mock")) == frozenset()

    def test_live_mode_puts_every_stage_on_the_backend(self):
        assert resolve_live_stages(_settings()) == frozenset(STAGE_KEYS)

    def test_an_explicit_list_wins_over_the_mode(self):
        settings = _settings(backend_mode="mock", live_stages=("risk_events",))
        assert resolve_live_stages(settings) == frozenset({"risk_events"})

    def test_no_base_url_means_nothing_can_go_live(self):
        settings = _settings(base_url="", live_stages=("risk_events",))
        assert resolve_live_stages(settings) == frozenset()

    def test_an_unknown_stage_name_is_ignored_not_fatal(self):
        settings = _settings(live_stages=("risk_events", "typo_stage"))
        assert resolve_live_stages(settings) == frozenset({"risk_events"})

    def test_an_empty_explicit_list_means_all_example(self):
        assert resolve_live_stages(_settings(live_stages=())) == frozenset()


class TestRouting:
    def _router(self, *live_stages: str) -> StageRouter:
        return StageRouter(
            RecordingAPI("live"), RecordingAPI("example"), frozenset(live_stages)
        )

    def test_each_stage_goes_to_its_configured_backend(self):
        router = self._router("mission_metadata", "briefing")
        for key in STAGE_KEYS:
            response = router.run_stage(get_stage(key), "M", {})
            expected = "live" if key in {"mission_metadata", "briefing"} else "example"
            assert response.payload["by"] == expected, key

    def test_the_response_is_stamped_with_the_answering_backend(self):
        router = self._router("risk_events")
        assert router.run_stage(get_stage("risk_events"), "M", {}).source == "live"
        assert router.run_stage(get_stage("methodology"), "M", {}).source == "example"

    def test_wiring_reports_every_stage(self):
        wiring = dict((spec.key, source) for spec, source in self._router("methodology").wiring())
        assert wiring["methodology"] == "live"
        assert wiring["briefing"] == "example"
        assert set(wiring) == set(STAGE_KEYS)

    def test_health_says_how_many_stages_are_live(self):
        detail = self._router("methodology", "risk_events").health().detail
        assert f"2/{len(STAGE_KEYS)} stages live" in detail


class TestBuildBackend:
    def test_mock_configuration_builds_the_example_backend(self):
        assert isinstance(build_backend(_settings(backend_mode="mock")), ExampleDataAPI)

    def test_fully_live_configuration_skips_the_router(self):
        backend = build_backend(_settings())
        assert isinstance(backend, HttpBackendAPI)
        backend.close()

    def test_a_partial_cutover_builds_a_router(self):
        backend = build_backend(_settings(live_stages=("mission_metadata",)))
        assert isinstance(backend, StageRouter)
        assert backend.live_stages == frozenset({"mission_metadata"})
        backend.close()

    def test_a_live_stage_without_a_base_url_falls_back_to_example_data(self):
        backend = build_backend(_settings(base_url="", live_stages=("risk_events",)))
        assert isinstance(backend, ExampleDataAPI)
