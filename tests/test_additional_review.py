"""An extra box extends one pallet, with observed counts and separate review history."""

from copy import deepcopy

import pytest

from smartfruit.additional_review import add_additional_review
from smartfruit.decision import confirm_inspection
from smartfruit.image_binding import validate_vision_import
from smartfruit.inspection import MANUAL_DEFECTS
from smartfruit.workflow import evaluate_inspection


def record(image_id="EXTRA", total=20, affected=1):
    return {
        "image_id": image_id,
        "partition": "test",
        "total_fruits": total,
        "oleocellosis_count": affected,
        "oleocellosis_pct": 100 * affected / total if total else 0,
        "mean_confidence": 0.9 if total else None,
        "fruit_predictions": [
            {
                "crop_id": f"{image_id}_{index}",
                "predicted_class": "con_oleocelosis" if index < affected else "sin_oleocelosis",
                "confidence": 0.9,
                "oleocellosis_probability": 0.9 if index < affected else 0.1,
            }
            for index in range(total)
        ],
    }


def manual(**changes):
    return {**{column["key"]: 0 for column in MANUAL_DEFECTS}, **changes}


@pytest.fixture
def capture():
    return {
        "qc_header": {
            "lot_id": "LOT_TEST", "inspection_date": "2026-11-15", "Level_Flag": "",
            "remarks": "Inspector notes retained",
        },
        "reason_source": "defect_summary",
        "samples": [
            {
                "sample_id": "S1", "pallet_id": "P1", "vision_records": [record("FIRST", 10, 1)],
                "vision_covers_sample": True,
                "qc_fields": {"pallet_id": "P1", "label_brand": "TEST_LABEL", **manual(scars=2)},
                "review_choice": "EXPAND", "observations": "First box",
            },
            {
                "sample_id": "S2", "pallet_id": "P2", "vision_records": [record("OTHER", 5, 0)],
                "vision_covers_sample": True,
                "qc_fields": {"pallet_id": "P2", **manual()}, "review_choice": "ESCALATE",
            },
        ],
    }


def request(capture, **changes):
    return {
        **deepcopy(capture), "sample_id": "S1", "inspector_decision": "EXTEND",
        "additional_review": {
            "vision_records": [record()], "manual_defects": manual(scars=3),
            "observations": "Second inspected box",
        },
        **changes,
    }


def test_extra_box_adds_counts_and_weighted_percentages_to_only_its_pallet(capture):
    payload = request(capture)
    original = deepcopy(payload)
    result = add_additional_review(payload)
    updated, report, detail = result["capture"], result["report"], result["review"]
    assert payload == original
    assert updated["samples"][1] == capture["samples"][1]
    fields = updated["samples"][0]["qc_fields"]
    assert fields["sample_count"] == 30 and fields["oleocellosis"] == 2
    assert fields["scars"] == 5 and fields["decay"] == 0
    summary = report["samples"][0]["inspection_summary"]
    assert summary["total_fruits"] == 30
    assert summary["oleocellosis_pct"] == pytest.approx(100 * 2 / 30)
    assert summary["oleocellosis_pct"] != pytest.approx((10 + 5) / 2)
    assert report["samples"][0]["defects"]["scars_pct"]["pct"] == pytest.approx(100 * 5 / 30)
    assert detail["qc_fields"]["sample_count"] == 20
    assert detail["manual_defects"]["scars"] == 3
    assert detail["observations"] == "Second inspected box"
    assert report["qc_header"]["reason"] == report["generated_reason"]
    assert updated["qc_header"]["remarks"] == capture["qc_header"]["remarks"]
    assert report["qc_header"]["Level_Flag"] == ""
    assert report["samples"][0]["inspector_final_decision"] is None


def test_history_records_initial_normalized_values_trigger_and_changed_suggestion(capture):
    result = add_additional_review(request(capture))
    target = result["capture"]["samples"][0]
    history = target["review_history"]
    assert history["initial"]["qc_fields"]["sample_count"] == 10
    assert history["initial"]["qc_fields"]["oleocellosis"] == 1
    assert history["initial"]["system_recommendation"] == "ESCALATE"
    assert history["additional"][0]["trigger_decision"] == "EXPAND"
    assert history["additional"][0]["system_recommendation_before"] == "ESCALATE"
    assert history["additional"][0]["system_recommendation_after"] == "EXPAND"
    assert target["review_choice"] == ""
    assert result["capture"]["samples"][1]["review_choice"] == "ESCALATE"
    assert result["report"]["samples"][0]["review_history"] == history
    assert len(target["image_bindings"]) == 2


def test_another_extra_box_keeps_initial_and_each_distinct_review(capture):
    first = add_additional_review(request(capture))["capture"]
    second_request = request(first)
    second_request["additional_review"]["vision_records"] = [record("THIRD", 10, 0)]
    second_request["additional_review"]["manual_defects"] = manual()
    result = add_additional_review(second_request)
    history = result["capture"]["samples"][0]["review_history"]
    assert history["initial"] == first["samples"][0]["review_history"]["initial"]
    assert [entry["review_number"] for entry in history["additional"]] == [2, 3]
    assert result["report"]["samples"][0]["qc_fields"]["sample_count"] == 40
    assert result["report"]["samples"][0]["qc_fields"]["scars"] == 5
    assert result["report"]["samples"][0]["inspection_summary"]["oleocellosis_pct"] == 5


def test_identical_duplicates_in_original_capture_still_count_only_once(capture):
    sample = capture["samples"][0]
    sample["vision_records"].append(deepcopy(sample["vision_records"][0]))
    result = add_additional_review(request(capture))
    updated = result["report"]["samples"][0]
    assert updated["qc_fields"]["sample_count"] == 30
    assert updated["review_history"]["initial"]["inspection_summary"]["total_fruits"] == 10
    assert updated["inspection_summary"]["duplicate_image_ids_ignored"] == ["FIRST"]
    assert len(updated["image_bindings"]) == 2


def test_partial_initial_coverage_cannot_be_extended_as_a_complete_sample(capture):
    capture["samples"][0]["vision_covers_sample"] = False
    payload = request(capture)
    original = deepcopy(payload)
    with pytest.raises(ValueError, match="cubren los frutos"):
        add_additional_review(payload)
    assert payload == original


@pytest.mark.parametrize("choice", ["STANDARD", "ESCALATE", "", None, False, {}])
def test_an_extra_box_requires_the_inspectors_extend_choice(capture, choice):
    payload = request(capture, inspector_decision=choice)
    original = deepcopy(payload)
    with pytest.raises(ValueError, match="EXTEND"):
        add_additional_review(payload)
    assert payload == original


@pytest.mark.parametrize("bad", ["existing_target", "existing_other", "duplicate_batch", "empty", "zero", "malformed"])
def test_bad_or_reused_json_never_partially_changes_a_pallet(capture, bad):
    payload = request(capture)
    value = payload["additional_review"]
    if bad == "existing_target":
        value["vision_records"] = [capture["samples"][0]["vision_records"][0]]
    elif bad == "existing_other":
        value["vision_records"] = [capture["samples"][1]["vision_records"][0]]
    elif bad == "duplicate_batch":
        value["vision_records"] = [record(), record()]
    elif bad == "empty":
        value["vision_records"] = []
    elif bad == "zero":
        value["vision_records"] = [record(total=0, affected=0)]
    else:
        value["vision_records"] = [record(), {"image_id": "BROKEN"}]
    original = deepcopy(payload)
    with pytest.raises(ValueError):
        add_additional_review(payload)
    assert payload == original


@pytest.mark.parametrize("bad", ["missing", "negative", "boolean", "fraction", "over_sample", "unknown", "pending"])
def test_manual_additional_defects_are_observed_not_implicitly_zero(capture, bad):
    payload = request(capture)
    fields = payload["additional_review"]["manual_defects"]
    if bad == "missing":
        del fields["scars"]
    elif bad == "unknown":
        fields["sample_count"] = 20
    else:
        fields["scars"] = {"negative": -1, "boolean": True, "fraction": 0.5, "over_sample": 21, "pending": None}[bad]
    original = deepcopy(payload)
    with pytest.raises(ValueError):
        add_additional_review(payload)
    assert payload == original


@pytest.mark.parametrize("change", ["current_count", "initial_count", "additional_count", "sequence", "trigger", "image"])
def test_evaluation_rejects_history_that_does_not_match_current_measurements(capture, change):
    updated = add_additional_review(request(capture))["capture"]
    target = updated["samples"][0]
    history = target["review_history"]
    if change == "current_count":
        target["qc_fields"]["scars"] = 9
    elif change == "initial_count":
        history["initial"]["qc_fields"]["scars"] = 0
    elif change == "additional_count":
        history["additional"][0]["manual_defects"]["scars"] = 0
    elif change == "sequence":
        history["additional"][0]["review_number"] = 5
    elif change == "trigger":
        history["additional"][0]["trigger_decision"] = "STANDARD"
    else:
        history["additional"][0]["vision_records"] = [record("UNLOGGED")]
    original = deepcopy(updated)
    with pytest.raises(ValueError):
        evaluate_inspection(updated)
    assert updated == original


def test_derived_round_totals_and_suggestions_are_recomputed_not_trusted(capture):
    updated = add_additional_review(request(capture))["capture"]
    history = updated["samples"][0]["review_history"]
    history["initial"]["system_recommendation"] = "STANDARD"
    history["additional"][0]["inspection_summary"]["total_fruits"] = 999
    history["additional"][0]["qc_fields"]["sample_count"] = 999
    history["additional"][0]["system_recommendation_after"] = "STANDARD"
    canonical = evaluate_inspection(updated)["samples"][0]["review_history"]
    assert canonical["initial"]["system_recommendation"] == "ESCALATE"
    assert canonical["additional"][0]["qc_fields"]["sample_count"] == 20
    assert canonical["additional"][0]["inspection_summary"]["total_fruits"] == 20
    assert canonical["additional"][0]["system_recommendation_after"] == "EXPAND"


def test_history_survives_confirmation_and_metadata_correction_without_assuming_approval(capture):
    updated = add_additional_review(request(capture))["capture"]
    updated["samples"][0]["qc_fields"]["label_brand"] = "Inspector corrected label"
    updated["samples"][0]["review_choice"] = "EXTEND"
    updated["qc_header"]["Level_Flag"] = 2
    evaluated = evaluate_inspection(updated)
    assert evaluated["samples"][0]["review_choice"] == "EXPAND"
    assert evaluated["samples"][0]["inspector_confirmed"] is False
    assert evaluated["samples"][0]["inspector_final_decision"] is None
    confirmed = confirm_inspection(evaluated, "Inspector TEST", {"S1": "EXTEND", "S2": "STANDARD"}, True)
    assert confirmed["samples"][0]["inspector_final_decision"] == "EXPAND"
    assert confirmed["samples"][0]["review_history"] == evaluated["samples"][0]["review_history"]
    assert confirmed["samples"][0]["qc_fields"]["label_brand"] == "Inspector corrected label"
    assert confirmed["samples"][0]["review_history"]["initial"]["qc_fields"]["label_brand"] == "TEST_LABEL"


def test_regular_import_cannot_append_photos_without_recording_an_additional_round(capture):
    updated = add_additional_review(request(capture))["capture"]
    with pytest.raises(ValueError, match="EXTEND"):
        validate_vision_import({**updated, "sample_id": "S1", "vision_records": [record("THIRD")]})


@pytest.mark.parametrize("choice", [None, "ACCEPT", False, 2, [], {}])
def test_review_choice_is_a_pending_valid_status_not_an_approval(capture, choice):
    capture["samples"][0]["review_choice"] = choice
    with pytest.raises(ValueError, match="decisión de revisión"):
        evaluate_inspection(capture)
