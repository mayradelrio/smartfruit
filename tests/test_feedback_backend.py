"""QC feedback: bounded boxes, explicit pallet omission and documented dominance."""

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from review_helpers import confirm_vision_records

from smartfruit.additional_review import add_additional_review
from smartfruit.app import create_app
from smartfruit.decision import confirm_inspection
from smartfruit.defect_dominance import DOMINANCE_METADATA, primary_defect
from smartfruit.image_binding import validate_vision_import
from smartfruit.inspection import MANUAL_DEFECTS
from smartfruit.reception import load_reception_manifest, resolve_reception_lot
from smartfruit.workflow import evaluate_inspection


def vision(image_id="FIRST", affected=0):
    return confirm_vision_records([{
        "image_id": image_id, "partition": "test", "total_fruits": 100,
        "oleocellosis_count": affected, "oleocellosis_pct": affected,
        "mean_confidence": 0.9,
        "fruit_predictions": [{
            "crop_id": f"{image_id}-{index}",
            "predicted_class": "con_oleocelosis" if index < affected else "sin_oleocelosis",
            "oleocellosis_probability": 0.9 if index < affected else 0.1,
            "confidence": 0.9,
        } for index in range(100)],
    }])


def manual(**changes):
    return {**{field["key"]: 0 for field in MANUAL_DEFECTS}, **changes}


def capture(**defects):
    return {
        "qc_header": {"lot_id": "LOT", "inspection_date": "2026-11-18", "Level_Flag": 3},
        "samples": [{
            "sample_id": "S1", "pallet_id": "P1", "vision_records": vision(),
            "vision_covers_sample": True, "qc_fields": manual(**defects),
        }],
    }


@pytest.mark.parametrize("scars,level,recommendation", [(0, 1, "STANDARD"), (5, 2, "EXTEND"), (20, 3, "EXTEND")])
def test_first_box_mapping_retains_human_level(scars, level, recommendation):
    report = evaluate_inspection(capture(scars=scars))
    assert report["samples"][0]["final_recommendation"] == recommendation
    assert report["samples"][0]["business_severity"]["business_max_level"] == level
    assert report["qc_header"]["Level_Flag"] == 3


def extended():
    return add_additional_review({
        **capture(scars=20), "sample_id": "S1", "inspector_decision": "EXTEND",
        "additional_review": {"vision_records": vision("SECOND"), "manual_defects": manual()},
    })


def test_second_box_completes_and_forged_third_history_is_rejected():
    result = extended()
    assert result["report"]["samples"][0]["final_recommendation"] == "COMPLETE"
    payload = result["capture"]
    payload["samples"][0]["review_history"]["additional"].append(
        deepcopy(payload["samples"][0]["review_history"]["additional"][0])
    )
    with pytest.raises(ValueError, match="máximo 2 cajas"):
        evaluate_inspection(payload)


def test_third_box_preview_is_rejected_before_import():
    payload = extended()["capture"]
    with pytest.raises(ValueError, match="2 cajas"):
        validate_vision_import({
            **payload, "sample_id": "S1", "vision_records": vision("THIRD"),
        }, additional_review=True)


@pytest.mark.parametrize("choice", ["ESCALATE", "COMPLETE", "EXTEND"])
def test_first_box_cannot_finalize_escalate_fake_complete_or_unfinished_extension(choice):
    with pytest.raises(ValueError):
        confirm_inspection(evaluate_inspection(capture()), "QC Test", {"S1": choice}, True)


def test_second_box_finalizes_only_complete():
    report = extended()["report"]
    assert confirm_inspection(report, "QC Test", {"S1": "COMPLETE"}, True)["inspector_confirmed"]
    with pytest.raises(ValueError, match="segunda caja"):
        confirm_inspection(report, "QC Test", {"S1": "EXTEND"}, True)


def lot_capture():
    lot = resolve_reception_lot(load_reception_manifest(
        "scan_code,lot_id,label_brand,country_origin,pallet_id,size_declared,expected_count_per_box\n"
        "P1,LOT,TEST,Peru,P1,100,100\nP2,LOT,TEST,Peru,P2,100,100\n"
    ), lot_id="LOT")
    result = capture()
    result["samples"][0]["reception"] = {
        "scan_input": lot["pallets"][0]["scan_input"], "records": lot["pallets"][0]["records"],
    }
    result["lot_reception"] = {
        "lot_id": "LOT", "records": lot["records"],
        "pallets": [
            {"pallet_id": "P1", "inspection_status": "COMPLETED", "selected_at": "2026-11-18T10:00:00-05:00", "completed_at": "2026-11-18T10:05:00-05:00"},
            {"pallet_id": "P2", "inspection_status": "SKIPPED", "skip_reason": "Muestreo QC"},
        ],
    }
    return result


def test_pallet_selection_skip_preserves_context_without_zero_defect_sample():
    payload = lot_capture()
    report = evaluate_inspection(payload)
    assert len(report["samples"]) == 1
    assert report["samples"][0]["pallet_id"] == "P1"
    assert report["lot_reception"]["pallets"][1]["inspection_status"] == "SKIPPED"
    assert report["lot_reception"]["pallets"][1]["skip_reason"] == "Muestreo QC"
    assert "qc_fields" not in report["lot_reception"]["pallets"][1]
    assert report["lot_summary"]["pallet_count"] == 1
    assert report["lot_summary"]["skipped_pallets"] == 1
    assert report["lot_summary"]["sample_count"] == 100
    assert confirm_inspection(report, "QC Test", {"S1": "STANDARD"}, True)["inspector_confirmed"]


def test_skipped_state_persists_in_report_and_source_and_print(tmp_path):
    payload = {
        **lot_capture(), "confirmed": True, "inspector_name": "QC Test",
        "final_decisions": {"S1": "STANDARD"},
    }
    with TestClient(create_app(tmp_path, False)) as client:
        response = client.post("/api/finalize", json=payload)
        assert response.status_code == 200, response.text
        saved = response.json()
        source = json.loads((tmp_path / saved["report_id"] / "source.json").read_text("utf-8"))
        assert source["lot_reception"]["pallets"][1]["inspection_status"] == "SKIPPED"
        report = client.get(saved["downloads"]["json"]).json()
        assert report["lot_reception"]["pallets"][1]["inspection_status"] == "SKIPPED"
        assert len(report["samples"]) == 1
        printable = client.get(saved["downloads"]["print"])
        assert "P2" in printable.text and "SKIPPED" in printable.text


@pytest.mark.parametrize("status", ["PENDING", "SELECTED", "IN_PROGRESS"])
def test_incomplete_pallet_is_visible_and_prevents_finalization(status):
    payload = lot_capture()
    payload["lot_reception"]["pallets"][1] = {"pallet_id": "P2", "inspection_status": status}
    report = evaluate_inspection(payload)
    assert report["lot_reception"]["pallets"][1]["inspection_status"] == status
    with pytest.raises(ValueError, match="paletas pendientes"):
        confirm_inspection(report, "QC Test", {"S1": "STANDARD"}, True)


def test_skipped_pallet_cannot_hide_an_inspected_box():
    payload = lot_capture()
    payload["samples"][0]["inspection_status"] = "SKIPPED"
    payload["lot_reception"]["pallets"][0] = {"pallet_id": "P1", "inspection_status": "SKIPPED"}
    with pytest.raises(ValueError, match="sin inspección"):
        evaluate_inspection(payload)


@pytest.mark.parametrize("status", ["PENDING", "SELECTED", "SKIPPED"])
def test_uninspected_pallet_cannot_hide_manual_defect_measurements(status):
    payload = lot_capture()
    payload["lot_reception"]["pallets"][1] = {"pallet_id": "P2", "inspection_status": status}
    omitted = deepcopy(payload["samples"][0])
    omitted.update(sample_id="S2", pallet_id="P2", inspection_status=status, vision_records=[])
    omitted["reception"]["records"] = [payload["lot_reception"]["records"][1]]
    omitted["reception"]["scan_input"] = "P2"
    omitted["qc_fields"] = {"scars": 1}
    payload["samples"].append(omitted)
    with pytest.raises(ValueError, match="sin inspección"):
        evaluate_inspection(payload)


@pytest.mark.parametrize("labels,expected", [
    (["decay", "skin_breakdown"], "decay"),
    (["styler", "oleocellosis"], "styler"),
    (["yellow", "oleocellosis"], "yellow_color"),
])
def test_dominance_requires_known_same_fruit_labels(labels, expected):
    assert primary_defect("FRUIT-1", labels) == expected
    assert DOMINANCE_METADATA["source"] == "QC user validation 2026-11-18"
    assert DOMINANCE_METADATA["status"] == "stakeholder-validated"


def test_dominance_does_not_invent_unknown_priorities_or_mutate_aggregate_counts():
    assert primary_defect("FRUIT-1", ["scar", "oleocellosis"]) is None
    assert primary_defect("FRUIT-1", ["mold", "decay"]) is None
    with pytest.raises(ValueError, match="mismo fruto"):
        primary_defect(None, ["decay", "styler"])
    report = evaluate_inspection(capture(decay=2, skin_breakdown=2))
    assert report["samples"][0]["qc_fields"]["decay"] == 2
    assert report["samples"][0]["qc_fields"]["skin_breakdown"] == 2
