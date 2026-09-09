"""The models must absorb backend drift — that is their whole job."""

from __future__ import annotations

from audit_front.models import (
    ActivityNode,
    Briefing,
    HistoricalRecommendations,
    HistoricalReports,
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
            HistoricalReports,
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


class TestAliasedListsAreCoerced:
    """Regression: coercion has to happen *after* the key is resolved.

    Per-model validators used to coerce before the base class renamed the key,
    so a scalar arriving under an alias failed validation — and `parsed()`
    swallowed that into an empty model, rendering a blank section rather than
    the data the backend actually sent.
    """

    def test_scalar_under_an_alias(self):
        assert MissionMetadata.model_validate({"country": "UNITED KINGDOM"}).countries == [
            "UNITED KINGDOM"
        ]

    def test_newline_string_under_an_alias(self):
        model = RiskEvents.model_validate({"analysis": "first\nsecond"})
        assert model.interpretation == ["first", "second"]

    def test_approach_alias_on_methodology(self):
        model = Methodology.model_validate({"approach": "do this\nthen that"})
        assert model.recommended_approach == ["do this", "then that"]

    def test_empty_dict_under_an_alias_means_no_records(self):
        assert HistoricalRecommendations.model_validate({"items": {}}).recommendations == []

    def test_positions_alias_on_reports(self):
        model = HistoricalReports.model_validate({"positions": "one position"})
        assert model.igad_positions == ["one position"]

    def test_briefing_axes_under_an_alias(self):
        model = Briefing.model_validate({"themes": "Asset risk"})
        assert [axis.title for axis in model.thematic_axes] == ["Asset risk"]

    def test_coercion_is_derived_from_the_annotations(self):
        # Every declared list field is covered, so a newly added one is tolerant
        # without anyone remembering to write a validator for it.
        coercers = HistoricalReports._list_coercers()
        assert set(coercers) == {"reports", "key_messages", "igad_positions", "implications"}


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

    def test_reports_found_infers_from_the_list(self):
        assert HistoricalReports(reports=[{"title": "X"}]).resolved_found is True
        assert HistoricalReports().resolved_found is False

    def test_third_line_reports_are_identified_by_their_line(self):
        model = HistoricalReports.model_validate(
            {
                "reports": [
                    {"report_id": "A", "line_of_defence": "3LOD"},
                    {"report_id": "B", "line_of_defence": "2LOD"},
                    {"report_id": "C", "line_of_defence": "3rd line"},
                    {"report_id": "D"},
                ]
            }
        )
        assert [r.report_id for r in model.third_line_reports] == ["A", "C"]

    def test_lines_covered_is_distinct_and_ordered(self):
        model = HistoricalReports.model_validate(
            {
                "reports": [
                    {"line_of_defence": "3LOD"},
                    {"line_of_defence": "2LOD"},
                    {"line_of_defence": "3LOD"},
                    {},
                ]
            }
        )
        assert model.lines_covered == ["3LOD", "2LOD", "Unspecified"]

    def test_positions_fall_back_to_the_per_report_ones(self):
        model = HistoricalReports.model_validate(
            {
                "reports": [
                    {"report_id": "IGAD-1", "igad_position": "framework unsatisfactory"},
                    {"report_id": "IGAD-2"},
                ]
            }
        )
        assert model.resolved_positions() == ["IGAD-1: framework unsatisfactory"]

    def test_stage_level_positions_win_over_the_per_report_ones(self):
        model = HistoricalReports.model_validate(
            {
                "igad_positions": ["the consolidated position"],
                "reports": [{"report_id": "IGAD-1", "igad_position": "per-report"}],
            }
        )
        assert model.resolved_positions() == ["the consolidated position"]

    def test_report_key_spellings_are_absorbed(self):
        model = HistoricalReports.model_validate(
            {
                "items": [
                    {
                        "id": "IGAD-2023-UK-0142",
                        "name": "Financial crime framework",
                        "lod": "3LOD",
                        "issuedBy": "IGAD",
                        "publicationDate": "2023-11-17",
                        "opinion": "Needs improvement",
                        "findings": "first point\nsecond point",
                        "position": "the position taken",
                    }
                ],
                "positions": "a single position",
            }
        )
        report = model.reports[0]
        assert report.report_id == "IGAD-2023-UK-0142"
        assert report.title == "Financial crime framework"
        assert report.line_of_defence == "3LOD"
        assert report.issuer == "IGAD"
        assert report.published_date == "2023-11-17"
        assert report.rating == "Needs improvement"
        assert report.key_messages == ["first point", "second point"]
        assert report.igad_position == "the position taken"
        assert model.igad_positions == ["a single position"]

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
