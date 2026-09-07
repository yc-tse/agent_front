"""The models must absorb backend drift — that is their whole job."""

from __future__ import annotations

from audit_front.models import (
    ActivityNode,
    Briefing,
    HistoricalRecommendations,
    Methodology,
    MissionMetadata,
    RiskEvents,
    ScopeUnderstanding,
    fix_mojibake,
)


class TestKeyNormalisation:
    def test_pascal_case_keys_land_on_fields(self):
        model = ScopeUnderstanding.model_validate(
            {
                "MissionName": "2026_Ayvens UK",
                "PrimaryScopeDriver": "Entity-driven",
                "ScopeCoverage": "Exact",
                "MissingDimensions": [],
            }
        )
        assert model.mission_name == "2026_Ayvens UK"
        assert model.primary_scope_driver == "Entity-driven"
        assert model.scope_coverage == "Exact"

    def test_prose_keys_land_on_fields(self):
        model = MissionMetadata.model_validate(
            {
                "Mission ID": "26-IRB/AYVENS-019",
                "Entities in scope": ["ALD AUTOMOTIVE LIMITED"],
                "Key risk families (RiskL1)": ["Data protection"],
                "Business lines involved": ["AVNS/UK"],
            }
        )
        assert model.mission_id == "26-IRB/AYVENS-019"
        assert model.entities == ["ALD AUTOMOTIVE LIMITED"]
        assert model.risk_families == ["Data protection"]
        assert model.business_lines == ["AVNS/UK"]

    def test_camel_case_and_snake_case_agree(self):
        camel = MissionMetadata.model_validate({"missionName": "X"})
        snake = MissionMetadata.model_validate({"mission_name": "X"})
        assert camel.mission_name == snake.mission_name == "X"

    def test_exact_field_name_wins_over_alias(self):
        model = MissionMetadata.model_validate({"mission_name": "exact", "name": "alias"})
        assert model.mission_name == "exact"

    def test_unknown_fields_are_kept_and_reported(self):
        model = MissionMetadata.model_validate({"mission_id": "X", "auditorInCharge": "R. Doe"})
        assert model.extras() == {"auditorInCharge": "R. Doe"}


class TestTolerance:
    def test_every_field_is_optional(self):
        for model_cls in (
            MissionMetadata,
            ScopeUnderstanding,
            RiskEvents,
            Methodology,
            HistoricalRecommendations,
            Briefing,
        ):
            assert model_cls() is not None

    def test_empty_dict_means_no_events(self):
        # The sample output spells an empty result set as `{}`.
        model = RiskEvents.model_validate({"events": {}})
        assert model.events == []
        assert model.resolved_count == 0

    def test_newline_separated_string_becomes_a_list(self):
        model = RiskEvents.model_validate({"interpretation": "- first\n- second\n\n"})
        assert model.interpretation == ["first", "second"]

    def test_scalar_becomes_a_list(self):
        model = MissionMetadata.model_validate({"countries": "UNITED KINGDOM"})
        assert model.countries == ["UNITED KINGDOM"]

    def test_briefing_accepts_bare_markdown(self):
        model = Briefing.model_validate("# Briefing\n\nSome text")
        assert model.markdown.startswith("# Briefing")


class TestMojibake:
    def test_repairs_cp1252_decoded_dashes(self):
        assert fix_mojibake("A22.01 â€“ Financial Crime") == "A22.01 – Financial Crime"

    def test_repair_runs_through_list_coercion(self):
        model = RiskEvents.model_validate({"interpretation": ["Losses â€“ none found"]})
        assert model.interpretation == ["Losses – none found"]


class TestActivityTree:
    def test_parses_code_and_label_from_a_string(self):
        node = ActivityNode.model_validate("A22.01.01 - AML")
        assert node.code == "A22.01.01"
        assert node.label == "AML"
        assert node.display == "A22.01.01 — AML"

    def test_string_without_separator_is_all_label(self):
        node = ActivityNode.model_validate("Compliance")
        assert node.label == "Compliance"
        assert node.code is None

    def test_nested_children_parse(self):
        model = MissionMetadata.model_validate(
            {
                "activities": [
                    {
                        "code": "A22",
                        "label": "Compliance",
                        "children": [{"code": "A22.01", "label": "Financial Crime"}],
                    }
                ]
            }
        )
        assert model.activities[0].children[0].code == "A22.01"
        assert len(model.activities[0].flatten()) == 2


class TestDerivedProperties:
    def test_scope_is_empty_when_no_filter_set(self):
        assert ScopeUnderstanding().is_empty is True
        assert ScopeUnderstanding(entity_filter=["A"]).is_empty is False

    def test_methodology_found_infers_from_references(self):
        assert Methodology(references=[{"title": "X"}]).resolved_found is True
        assert Methodology().resolved_found is False
        # An explicit flag overrides the inference.
        assert Methodology(found=False, references=[{"title": "X"}]).resolved_found is False

    def test_open_items_excludes_closed_statuses(self):
        model = HistoricalRecommendations.model_validate(
            {
                "recommendations": [
                    {"rec_id": "A", "status": "Open"},
                    {"rec_id": "B", "status": "Closed"},
                    {"rec_id": "C", "status": "implemented"},
                ]
            }
        )
        assert [r.rec_id for r in model.open_items] == ["A"]
