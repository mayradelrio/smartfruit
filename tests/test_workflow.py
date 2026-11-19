"""Integration checks for QC capture, decisions, and the optional signal."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from smartfruit.decision import confirm_inspection
from smartfruit.workflow import evaluate_inspection

MANUAL_COUNTS = (
    "decay",
    "styler",
    "mold",
    "soft",
    "skin_breakdown",
    "wounds",
    "int_dryness",
    "black_tips",
    "skin_defect",
    "scars",
    "white_stain",
    "blanching",
    "yellow_color",
    "stain",
    "undersize",
)


@pytest.fixture
def capture():
    examples = Path(__file__).resolve().parents[1] / "examples" / "vision"
    records = [
        json.loads((examples / f"IMG_{image}.json").read_text("utf-8"))
        for image in (6426, 6427, 6428)
    ]
    return {
        "qc_header": {
            "inspection_date": "2026-11-13",
            "lot_id": "LOT_DEMO_001",
            "Level_Flag": 1,
        },
        "samples": [
            {
                "sample_id": "SAMPLE_DEMO_001",
                "pallet_id": "PALLET_DEMO_01",
                "vision_records": records,
                "vision_covers_sample": True,
                "qc_fields": {
                    **dict.fromkeys(MANUAL_COUNTS, 0),
                    "sample_count": 36,
                    "label_brand": "DEMO",
                    "pulp_temp": 50.2,
                },
                "observations": "Datos manuales de demostración.",
            }
        ],
        "observations": "Reporte de prueba.",
    }


def test_off_evaluates_real_vision_and_preserves_capture(capture):
    original = deepcopy(capture)
    provider = Mock(side_effect=AssertionError("OFF must not call a model"))
    report = evaluate_inspection(capture, use_predictive=False, provider=provider)
    sample = report["samples"][0]

    assert sample["inspection_summary"]["total_fruits"] == 36
    assert sample["inspection_summary"]["oleocellosis_count"] == 3
    assert sample["inspection_summary"]["oleocellosis_pct"] == pytest.approx(100 * 3 / 36)
    assert sample["qc_fields"]["oleocellosis"] == 3
    assert sample["business_severity"]["business_max_level"] == 2
    assert sample["final_recommendation"] == "EXPAND"
    assert "Oleocelosis" in sample["recommendation_reasons"]
    assert sample["predictive"]["enabled"] is False
    assert "predicted_loss_pct" not in sample["predictive"]
    assert sample["human_confirmation_required"] is True
    assert report["inspector_confirmed"] is False
    assert report["qc_header"]["Level_Flag"] == 1
    assert capture == original
    provider.assert_not_called()


@pytest.mark.parametrize("field", MANUAL_COUNTS)
def test_each_manual_defect_is_required_even_without_a_business_rule(capture, field):
    del capture["samples"][0]["qc_fields"][field]
    with pytest.raises(ValueError):
        evaluate_inspection(capture)


@pytest.mark.parametrize("value", [None, "", "0", -1, 37, 1.5, True, [], {}])
def test_invalid_manual_count_is_not_converted_to_zero(capture, value):
    capture["samples"][0]["qc_fields"]["scars"] = value
    with pytest.raises(ValueError):
        evaluate_inspection(capture)


@pytest.mark.parametrize("coverage", [False, None, "true", 1])
def test_vision_must_explicitly_cover_the_same_sample(capture, coverage):
    capture["samples"][0]["vision_covers_sample"] = coverage
    with pytest.raises(ValueError):
        evaluate_inspection(capture)


def test_manual_denominator_cannot_differ_from_vision(capture):
    capture["samples"][0]["qc_fields"]["sample_count"] = 72
    with pytest.raises(ValueError, match="Sample"):
        evaluate_inspection(capture)


def test_vision_count_cannot_be_overridden_manually(capture):
    capture["samples"][0]["qc_fields"]["oleocellosis"] = 0
    with pytest.raises(ValueError, match="Oleocellosis"):
        evaluate_inspection(capture)


def test_repeated_photo_does_not_inflate_a_sample(capture):
    records = capture["samples"][0]["vision_records"]
    records.append(deepcopy(records[0]))
    sample = evaluate_inspection(capture)["samples"][0]
    summary = sample["inspection_summary"]
    assert summary["total_fruits"] == 36
    assert summary["oleocellosis_count"] == 3
    assert summary["images_processed"] == 3
    assert summary["duplicate_image_ids_ignored"] == ["IMG_6426"]
    assert sample["final_recommendation"] == "EXPAND"


def test_same_photo_cannot_be_assigned_to_two_samples(capture):
    second = deepcopy(capture["samples"][0])
    second.update(sample_id="SECOND_SAMPLE", pallet_id="SECOND_PALLET")
    capture["samples"].append(second)
    with pytest.raises(ValueError, match="más de una muestra"):
        evaluate_inspection(capture)


def test_manual_mold_overrides_lower_vision_severity_by_existing_rule(capture):
    capture["samples"][0]["qc_fields"]["mold"] = 1  # 2.78%, above the existing 1% rule.
    sample = evaluate_inspection(capture)["samples"][0]
    assert sample["final_recommendation"] == "ESCALATE"
    assert sample["business_severity"]["business_max_level"] == 3
    assert sample["recommendation_reasons"] == ["Moho"]


def test_unmapped_defect_is_retained_and_rule_coverage_is_explicit(capture):
    capture["samples"][0]["qc_fields"]["soft"] = 2
    sample = evaluate_inspection(capture)["samples"][0]
    assert sample["qc_fields"]["soft"] == 2
    assert "Soft" in sample["rule_coverage"]["not_evaluated"]
    assert len(sample["rule_coverage"]["evaluated"]) == 8
    assert len(sample["rule_coverage"]["not_evaluated"]) == 8


@pytest.mark.parametrize(
    "name,decisions,confirmed",
    [
        ("Inspector", {"SAMPLE_DEMO_001": "STANDARD"}, False),
        ("", {"SAMPLE_DEMO_001": "STANDARD"}, True),
        ("Inspector", {}, True),
        ("Inspector", {"SAMPLE_DEMO_001": "ACCEPT"}, True),
        ("Inspector", {"SAMPLE_DEMO_001": "STANDARD", "extra": "STANDARD"}, True),
    ],
)
def test_confirmation_requires_name_explicit_consent_and_each_decision(
    capture,
    name,
    decisions,
    confirmed,
):
    report = evaluate_inspection(capture)
    with pytest.raises(ValueError):
        confirm_inspection(report, name, decisions, confirmed)


def test_inspector_can_choose_standard_without_rewriting_recommendation(capture):
    draft = evaluate_inspection(capture)
    confirmed = confirm_inspection(
        draft,
        " Inspector Demo ",
        {"SAMPLE_DEMO_001": "STANDARD"},
        confirmed=True,
    )
    assert confirmed["inspector_name"] == "Inspector Demo"
    assert confirmed["inspector_confirmed"] is True
    assert confirmed["confirmed_at"]
    assert confirmed["qc_header"]["Level_Flag"] == 1
    sample = confirmed["samples"][0]
    assert sample["inspector_final_decision"] == "STANDARD"
    assert sample["inspector_confirmed"] is True
    assert sample["final_recommendation"] == "EXPAND"
    assert sample["business_severity"]["recommendation"] == "EXPAND"
    assert draft["samples"][0]["inspector_final_decision"] is None


def test_every_distinct_sample_requires_its_own_final_decision(capture):
    first = capture["samples"][0]
    second = deepcopy(first)
    second.update(sample_id="SECOND_SAMPLE", pallet_id="SECOND_PALLET")
    second["vision_records"] = second["vision_records"][1:]
    second["qc_fields"]["sample_count"] = 24
    first["vision_records"] = first["vision_records"][:1]
    first["qc_fields"]["sample_count"] = 12
    capture["samples"].append(second)
    draft = evaluate_inspection(capture)
    assert len(draft["samples"]) == 2
    with pytest.raises(ValueError, match="cada muestra"):
        confirm_inspection(draft, "Inspector", {"SAMPLE_DEMO_001": "STANDARD"}, True)
    report = confirm_inspection(
        draft,
        "Inspector",
        {"SAMPLE_DEMO_001": "STANDARD", "SECOND_SAMPLE": "EXPAND"},
        True,
    )
    assert all(sample["inspector_confirmed"] for sample in report["samples"])


@pytest.mark.parametrize("provider", [None, Mock(side_effect=RuntimeError("provider failed"))])
def test_predictive_on_missing_or_failing_never_blocks_rules(capture, provider):
    sample = evaluate_inspection(capture, use_predictive=True, provider=provider)["samples"][0]
    assert sample["final_recommendation"] == "EXPAND"
    assert sample["predictive"]["enabled"] is True
    assert sample["predictive"]["experimental"] is True
    assert sample["predictive"]["status"] == "unavailable"
    assert sample["predictive"]["predicted_loss_pct"] is None


def test_predictive_signal_is_additional_and_does_not_change_recommendation(capture):
    provider = Mock(return_value={"predicted_loss_pct": 90.0})
    sample = evaluate_inspection(capture, use_predictive=True, provider=provider)["samples"][0]
    provider.assert_called_once()
    assert sample["predictive"]["predicted_loss_pct"] == 90.0
    assert sample["final_recommendation"] == "EXPAND"
    assert sample["business_severity"]["business_max_level"] == 2
