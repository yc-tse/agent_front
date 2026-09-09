"""The example data loader: the directory is the registry.

Nothing in the application names a mission. Adding a sample mission is adding a
file, so these tests are mostly about that contract holding — discovery by
scan, keying on the id inside the document, and error messages that say which
file to fix.
"""

from __future__ import annotations

import json

import pytest
from sample_missions import SAMPLE_MISSIONS

from audit_front import example_backend
from audit_front.api import BackendError
from audit_front.example_backend import (
    EXAMPLE_DIR,
    ExampleDataAPI,
    available_missions,
    load_mission,
    load_payload,
    missing_stages,
    mission_file,
    reload_example_data,
    skipped_files,
    suggested_filename,
)
from audit_front.pipeline import STAGE_KEYS, get_stage


@pytest.fixture
def example_dir(tmp_path, monkeypatch):
    """Point the loader at a throwaway directory."""
    monkeypatch.setattr(example_backend, "EXAMPLE_DIR", tmp_path)
    reload_example_data()
    yield tmp_path
    reload_example_data()


def write_mission(folder, filename: str, **overrides) -> dict:
    document = {
        "mission_id": "TEST/M-001",
        "mission_name": "A test mission",
        "stages": {key: {"stage": key} for key in STAGE_KEYS},
    }
    document.update(overrides)
    (folder / filename).write_text(json.dumps(document), encoding="utf-8")
    reload_example_data()
    return document


class TestBundledMissions:
    def test_the_fixture_missions_are_actually_bundled(self):
        """Renaming or removing a mission file should fail here, once, loudly.

        Without this the same breakage surfaces as dozens of confusing
        "mission has no example data" failures across the whole suite.
        """
        bundled = {mission_id for mission_id, _ in available_missions()}
        missing = [m for m in SAMPLE_MISSIONS if m not in bundled]
        assert not missing, f"no example file for {missing}; bundled: {sorted(bundled)}"

    def test_one_file_per_mission(self):
        files = sorted(EXAMPLE_DIR.glob("*.json"))
        assert len(files) == len(available_missions())
        assert not [p for p in EXAMPLE_DIR.iterdir() if p.is_dir()], (
            "example data should be flat files, one per mission"
        )

    @pytest.mark.parametrize("mission_id", SAMPLE_MISSIONS)
    def test_each_file_carries_its_id_name_and_every_stage(self, mission_id):
        document = load_mission(mission_id)
        assert document["mission_id"] == mission_id
        assert document["mission_name"].strip()
        assert set(document["stages"]) == set(STAGE_KEYS)
        assert missing_stages(mission_id) == []

    def test_the_name_shown_in_the_sidebar_comes_from_the_file(self):
        for mission_id, mission_name in available_missions():
            assert mission_name == load_mission(mission_id)["mission_name"]


class TestDiscovery:
    def test_a_dropped_in_file_is_found_without_any_code_change(self, example_dir):
        assert available_missions() == []
        write_mission(example_dir, "anything.json")
        assert available_missions() == [("TEST/M-001", "A test mission")]

    def test_the_filename_does_not_have_to_match_the_id(self, example_dir):
        write_mission(example_dir, "not-the-mission-id.json")
        assert mission_file("TEST/M-001").name == "not-the-mission-id.json"

    def test_lookup_is_case_insensitive_and_ignores_surrounding_space(self, example_dir):
        write_mission(example_dir, "m.json")
        assert load_payload("  test/m-001  ", "briefing") == {"stage": "briefing"}

    def test_several_missions_coexist(self, example_dir):
        write_mission(example_dir, "a.json", mission_id="TEST/A", mission_name="A")
        write_mission(example_dir, "b.json", mission_id="TEST/B", mission_name="B")
        assert available_missions() == [("TEST/A", "A"), ("TEST/B", "B")]

    def test_edits_take_effect_without_a_restart(self, example_dir):
        write_mission(example_dir, "m.json")
        assert load_payload("TEST/M-001", "briefing") == {"stage": "briefing"}

        # Same file, new content — the payload is re-read on every call so that
        # dropping in a captured backend response does not need a redeploy.
        document = load_mission("TEST/M-001")
        document["stages"]["briefing"] = {"objective": "edited on disk"}
        (example_dir / "m.json").write_text(json.dumps(document), encoding="utf-8")
        assert load_payload("TEST/M-001", "briefing") == {"objective": "edited on disk"}

    def test_a_file_without_a_mission_id_is_skipped_not_fatal(self, example_dir):
        (example_dir / "notes.json").write_text(json.dumps({"hello": "world"}), encoding="utf-8")
        write_mission(example_dir, "real.json")
        assert available_missions() == [("TEST/M-001", "A test mission")]

    def test_a_malformed_file_does_not_hide_the_valid_ones(self, example_dir):
        (example_dir / "broken.json").write_text("{ not json", encoding="utf-8")
        write_mission(example_dir, "real.json")
        assert available_missions() == [("TEST/M-001", "A test mission")]

    def test_an_empty_directory_is_not_an_error(self, example_dir):
        assert available_missions() == []
        assert ExampleDataAPI(latency=False).health().ok is True


class TestErrorMessages:
    """Every failure has to say which file to create or fix."""

    def test_an_unknown_mission_names_the_file_to_create(self, example_dir):
        write_mission(example_dir, "m.json")
        with pytest.raises(BackendError) as excinfo:
            load_payload("99-XXX/NOPE-001", "briefing")
        message = str(excinfo.value)
        assert "99-XXX_NOPE-001.json" in message
        assert "TEST/M-001" in message, "the message should list what is available"

    def test_a_missing_stage_names_the_file_and_the_key(self, example_dir):
        stages = {key: {"stage": key} for key in STAGE_KEYS if key != "briefing"}
        write_mission(example_dir, "partial.json", stages=stages)

        assert missing_stages("TEST/M-001") == ["briefing"]
        with pytest.raises(BackendError) as excinfo:
            load_payload("TEST/M-001", "briefing")
        message = str(excinfo.value)
        assert '"briefing" entry under "stages"' in message
        assert "partial.json" in message

    def test_a_missing_stages_object_is_reported_clearly(self, example_dir):
        write_mission(example_dir, "m.json", stages="not an object")
        with pytest.raises(BackendError) as excinfo:
            load_payload("TEST/M-001", "briefing")
        assert "no 'stages' object" in str(excinfo.value)

    def test_a_file_broken_after_the_scan_names_itself(self, example_dir):
        write_mission(example_dir, "m.json")
        available_missions()  # index built while the file was still valid

        (example_dir / "m.json").write_text("{ not json", encoding="utf-8")
        with pytest.raises(BackendError) as excinfo:
            load_mission("TEST/M-001")
        assert "m.json is not valid JSON" in str(excinfo.value)

    def test_an_unusable_file_is_named_rather_than_silently_ignored(self, example_dir):
        # Being told "no missions" while a broken file sits in the directory is
        # a maddening thing to debug, so the message lists what was skipped.
        (example_dir / "broken.json").write_text("{ not json", encoding="utf-8")
        (example_dir / "nameless.json").write_text('{"stages": {}}', encoding="utf-8")
        reload_example_data()

        assert skipped_files() == {
            "broken.json": "Example mission file broken.json is not valid JSON",
            "nameless.json": 'no "mission_id" field',
        }
        with pytest.raises(BackendError) as excinfo:
            load_mission("TEST/M-001")
        message = str(excinfo.value)
        assert "broken.json" in message
        assert "nameless.json" in message

    def test_suggested_filenames_are_filesystem_safe(self):
        assert suggested_filename("26-IRB/AYVENS-019") == "26-IRB_AYVENS-019.json"
        assert suggested_filename("a b/c:d") == "a_b_c_d.json"
        assert suggested_filename("   ") == "mission.json"


class TestServingFromFiles:
    def test_a_stage_is_served_from_its_entry_in_the_document(self, example_dir):
        write_mission(example_dir, "m.json")
        response = ExampleDataAPI(latency=False).run_stage(
            get_stage("methodology"), "TEST/M-001", {}
        )
        assert response.payload == {"stage": "methodology"}
        assert response.source == "example"

    def test_the_served_payload_is_a_copy(self, example_dir):
        write_mission(example_dir, "m.json")
        payload = load_payload("TEST/M-001", "briefing")
        payload["mutated"] = True
        assert "mutated" not in load_payload("TEST/M-001", "briefing")

    def test_a_non_object_stage_payload_is_still_usable(self, example_dir):
        write_mission(
            example_dir,
            "m.json",
            stages={**{k: {} for k in STAGE_KEYS}, "risk_events": [{"event_id": "A"}]},
        )
        assert load_payload("TEST/M-001", "risk_events") == {"items": [{"event_id": "A"}]}
