"""Physical box completion, manifest selection and per-box count comparisons."""

import base64
import json
import runpy
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient
from review_helpers import confirm_vision_record

from smartfruit.additional_review import add_additional_review
from smartfruit.app import create_app
from smartfruit.box_inspection import summarize_box_inspection
from smartfruit.inspection import MANUAL_DEFECTS
from smartfruit.vision import aggregate_vision_sample
from smartfruit.workflow import evaluate_inspection


def vision(image_id, total=12, affected=0):
    return confirm_vision_record({
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
    })


def manual():
    return {column["key"]: 0 for column in MANUAL_DEFECTS}


def manifest_row(**changes):
    return {
        "scan_code": "PALLET_01", "lot_id": "LOT_TEST", "pallet_id": "PALLET_01",
        "label_brand": "TEST", "country_origin": "TEST", "size_declared": "150",
        "expected_count_per_box": "150", **changes,
    }


def metadata(**changes):
    return {
        "sample_box_id": "BOX_001", "status": "completed", "coverage_confirmed": True,
        "manifest_record_index": None, **changes,
    }


@pytest.fixture
def capture():
    records = [vision(f"GROUP_{index:02}", 12, int(index < 9)) for index in range(12)]
    records.append(vision("GROUP_12", 2))
    return {
        "qc_header": {"lot_id": "LOT_TEST", "inspection_date": "2026-11-15"},
        "samples": [{
            "sample_id": "SAMPLE_001", "pallet_id": "PALLET_01", "vision_records": records,
            "vision_covers_sample": True, "qc_fields": manual(), "box_inspection": metadata(),
            "reception": {"scan_input": "PALLET_01", "records": [manifest_row()]},
        }],
    }


def summary(total=146):
    return aggregate_vision_sample([vision("GROUP", total)], "SAMPLE")["vision_summary"]


def test_multiple_photos_count_unique_fruits_and_allow_explicitly_closed_shortage(capture):
    capture["samples"][0]["vision_records"].append(
        deepcopy(capture["samples"][0]["vision_records"][0])
    )
    before = deepcopy(capture)
    report = evaluate_inspection(capture)["samples"][0]
    box = report["box_inspection"]
    assert capture == before
    assert box["actual_count"] == 146
    assert box["images_processed"] == 13
    assert box["expected_count_per_box"] == 150
    assert box["count_difference"] == -4
    assert box["missing_count"] == 4 and box["excess_count"] == 0
    assert box["count_deviation_pct"] == pytest.approx(-2.6666666667)
    assert box["comparison_status"] == "shortage"
    assert box["oleocellosis_count"] == 9
    assert box["oleocellosis_pct"] == pytest.approx(100 * 9 / 146)
    assert report["box_inspections"] == [box]


@pytest.mark.parametrize("total,status,difference", [(150, "matched", 0), (153, "excess", 3)])
def test_count_comparison_has_no_invented_tolerance(total, status, difference):
    box = summarize_box_inspection(metadata(), summary(total), {"records": [manifest_row()]})
    assert box["comparison_status"] == status
    assert box["count_difference"] == difference
    assert box["excess_count"] == max(difference, 0)


def test_draft_counts_do_not_automatically_close_box_even_when_expected_matches():
    box = summarize_box_inspection(
        metadata(status="capturing", coverage_confirmed=False), summary(150),
        {"records": [manifest_row()]},
    )
    assert box["status"] == "capturing" and box["comparison_status"] == "matched"


@pytest.mark.parametrize("changes", [
    {"status": "capturing", "coverage_confirmed": False},
    {"coverage_confirmed": False}, {"coverage_confirmed": "true"},
])
def test_incomplete_box_cannot_produce_evaluated_recommendation(capture, changes):
    capture["samples"][0]["box_inspection"].update(changes)
    with pytest.raises(ValueError, match="caja|cobertura"):
        evaluate_inspection(capture)


@pytest.mark.parametrize("expected", ["", "0"])
def test_missing_expected_count_stays_unknown_instead_of_zero_or_sample_size(expected):
    box = summarize_box_inspection(
        metadata(), summary(), {"records": [manifest_row(expected_count_per_box=expected)]},
        require_completed=True,
    )
    assert box["expected_count_per_box"] is None
    assert box["count_difference"] is None and box["count_deviation_pct"] is None
    assert box["missing_count"] is None and box["excess_count"] is None
    assert box["comparison_status"] == "unavailable"


def test_no_manifest_never_uses_client_supplied_expected_or_inferred_size(capture):
    sample = capture["samples"][0]
    sample.pop("reception")
    sample["box_inspection"].update(expected_count_per_box=999, actual_count=999)
    sample["qc_fields"]["size"] = "150"
    box = evaluate_inspection(capture)["samples"][0]["box_inspection"]
    assert box["expected_count_per_box"] is None and box["actual_count"] == 146


def test_mixed_manifest_requires_selection_then_compares_the_selected_box(capture):
    sample = capture["samples"][0]
    sample["reception"]["records"].append(
        manifest_row(size_declared="200", expected_count_per_box="200")
    )
    draft = summarize_box_inspection(
        metadata(status="capturing", coverage_confirmed=False), summary(), sample["reception"]
    )
    assert draft["comparison_status"] == "selection_required"
    assert draft["expected_count_per_box"] is None
    with pytest.raises(ValueError, match="selecciona la línea"):
        evaluate_inspection(capture)
    sample["box_inspection"]["manifest_record_index"] = 1
    box = evaluate_inspection(capture)["samples"][0]["box_inspection"]
    assert box["expected_count_per_box"] == 200
    assert box["count_difference"] == -54
    assert box["size_declared"] == "200"


@pytest.mark.parametrize("index", [-1, 1, True, "0"])
def test_manifest_selector_must_refer_to_this_pallet_records(index):
    with pytest.raises(ValueError, match="línea válida"):
        summarize_box_inspection(
            metadata(manifest_record_index=index), summary(), {"records": [manifest_row()]}
        )


def test_derived_values_and_manual_denominators_cannot_replace_vision_counts(capture):
    sample = capture["samples"][0]
    sample["box_inspection"].update(
        expected_count_per_box=1, count_difference=0, actual_count=1, missing_count=0
    )
    report = evaluate_inspection(capture)["samples"][0]
    assert report["box_inspection"]["count_difference"] == -4
    assert report["qc_fields"]["sample_count"] == 146
    legacy = deepcopy(capture)
    legacy["samples"][0].pop("box_inspection")
    assert evaluate_inspection(legacy)["samples"][0]["final_recommendation"] == report[
        "final_recommendation"
    ]


def additional_request(capture, box_id="BOX_002", total=151, suffix="EXTRA"):
    return {
        **deepcopy(capture), "sample_id": "SAMPLE_001", "inspector_decision": "EXPAND",
        "additional_review": {
            "vision_records": [vision(suffix, total)], "manual_defects": manual(),
            "box_inspection": metadata(sample_box_id=box_id),
        },
    }


def test_additional_boxes_compare_individually_and_preserve_pallet_accumulation(capture):
    result = add_additional_review(additional_request(capture))
    sample = result["report"]["samples"][0]
    first, second = sample["box_inspections"]
    assert first["sample_box_id"] == "BOX_001" and second["sample_box_id"] == "BOX_002"
    assert first["actual_count"] == 146 and first["count_difference"] == -4
    assert second["actual_count"] == 151 and second["count_difference"] == 1
    assert sample["inspection_summary"]["total_fruits"] == 297
    assert sample["box_inspection"] == first
    assert sample["review_history"]["initial"]["box_inspection"] == first
    assert sample["review_history"]["additional"][0]["box_inspection"] == second
    before = deepcopy(result["capture"])
    with pytest.raises(ValueError, match="2 cajas"):
        add_additional_review(additional_request(
            result["capture"], box_id="BOX_003", total=150, suffix="THIRD"
        ))
    assert result["capture"] == before


@pytest.mark.parametrize("change", ["duplicate_id", "unclosed", "missing_metadata"])
def test_invalid_additional_box_does_not_mutate_the_capture(capture, change):
    request = additional_request(capture)
    box = request["additional_review"]["box_inspection"]
    if change == "duplicate_id":
        box["sample_box_id"] = "BOX_001"
    elif change == "unclosed":
        box.update(status="capturing", coverage_confirmed=False)
    else:
        request["additional_review"].pop("box_inspection")
    before = deepcopy(request)
    with pytest.raises(ValueError, match="caja|sample_box_id"):
        add_additional_review(request)
    assert request == before


def test_history_box_measurements_are_recomputed_and_initial_identity_is_checked(capture):
    updated = add_additional_review(additional_request(capture))["capture"]
    history = updated["samples"][0]["review_history"]
    history["initial"]["box_inspection"]["actual_count"] = 999
    history["additional"][0]["box_inspection"]["count_difference"] = 999
    sample = evaluate_inspection(updated)["samples"][0]
    assert [box["count_difference"] for box in sample["box_inspections"]] == [-4, 1]
    updated["samples"][0]["box_inspection"]["sample_box_id"] = "CHANGED"
    with pytest.raises(ValueError, match="caja inicial"):
        evaluate_inspection(updated)


def test_legacy_capture_without_box_metadata_remains_compatible(capture):
    capture["samples"][0].pop("box_inspection")
    report = evaluate_inspection(capture)["samples"][0]
    assert "box_inspection" not in report and "box_inspections" not in report


@pytest.fixture
def transports(tmp_path):
    root = Path(__file__).resolve().parents[1]
    dispatch = runpy.run_path(str(root / "hosting/browser/browser_api.py"))[
        "smartfruit_browser_api"
    ]

    def browser(path, payload, report_id=""):
        return json.loads(dispatch("POST", path, json.dumps(payload), report_id))

    with TestClient(create_app(tmp_path, False), raise_server_exceptions=False) as client:
        yield client, browser


def test_box_capture_import_evaluate_and_confirm_preserve_metrics_in_both_transports(
    capture, transports, tmp_path,
):
    client, browser = transports
    sample = capture["samples"][0]
    records = sample["vision_records"]
    sample.update(
        vision_records=[], box_inspection=metadata(status="capturing", coverage_confirmed=False)
    )
    request = {**capture, "sample_id": sample["sample_id"], "vision_records": records}
    original = deepcopy(request)
    imported = client.post("/api/vision/import", json=request)
    assert imported.status_code == 200, imported.text
    assert browser("/api/vision/import", request)["body"] == imported.json()
    assert request == original
    assert imported.json()["inspection_summary"]["images_processed"] == 13
    assert imported.json()["inspection_summary"]["total_fruits"] == 146
    sample.update(
        vision_records=imported.json()["vision_records"],
        image_bindings=imported.json()["image_bindings"],
    )
    assert client.post("/api/evaluate", json=capture).status_code == 422
    assert browser("/api/evaluate", capture)["status"] == 422
    sample["box_inspection"] = metadata()
    preview = client.post("/api/evaluate", json=capture)
    assert preview.status_code == 200, preview.text
    assert preview.json() == browser("/api/evaluate", capture)["body"]
    box = preview.json()["samples"][0]["box_inspection"]
    assert box["images_processed"] == 13 and box["actual_count"] == 146
    assert box["expected_count_per_box"] == 150 and box["count_difference"] == -4
    assert box["missing_count"] == 4

    capture.update(
        confirmed=True, inspector_name="Inspector TEST",
        final_decisions={"SAMPLE_001": "STANDARD"},
    )
    finalized = client.post("/api/finalize", json=capture)
    assert finalized.status_code == 200, finalized.text
    result = finalized.json()
    browser_result = browser("/api/finalize", capture, result["report_id"])
    assert browser_result["status"] == 200
    stored_report = json.loads((tmp_path / result["report_id"] / "report.json").read_text("utf-8"))
    stored_capture = json.loads((tmp_path / result["report_id"] / "source.json").read_text("utf-8"))
    assert stored_capture == capture == browser_result["storage"]["source"]
    assert stored_report == result["report"] == client.get(result["downloads"]["json"]).json()
    for report in (stored_report, browser_result["storage"]["report"]):
        item = report["samples"][0]
        assert item["box_inspection"] == box and item["box_inspections"] == [box]
        assert item["inspector_final_decision"] == "STANDARD"
        assert item["image_bindings"] == imported.json()["image_bindings"]
    # The browser storage envelope carries a real workbook for its IndexedDB transaction.
    workbook = openpyxl.load_workbook(
        BytesIO(base64.b64decode(browser_result["storage"]["xlsx_base64"])), data_only=True
    )
    assert workbook["Report"]["I16"].value == 146
    assert client.get(result["downloads"]["xlsx"]).status_code == 200
    assert "Caja BOX_001" in client.get(result["downloads"]["print"]).text


@pytest.mark.parametrize("endpoint", [
    "/api/evaluate", "/api/export", "/api/report/print", "/api/finalize",
])
def test_capturing_box_cannot_be_exported_or_persisted_by_either_transport(
    capture, transports, tmp_path, endpoint,
):
    client, browser = transports
    capture["samples"][0]["box_inspection"] = metadata(
        status="capturing", coverage_confirmed=False
    )
    capture.update(
        confirmed=True, inspector_name="Inspector TEST",
        final_decisions={"SAMPLE_001": "STANDARD"},
    )
    before = deepcopy(capture)
    local = client.post(endpoint, json=capture)
    remote = browser(endpoint, capture)
    assert local.status_code == remote["status"] == 422
    assert local.json() == remote["body"]
    assert "finaliza" in local.json()["detail"]
    assert "storage" not in remote
    assert list(tmp_path.iterdir()) == []
    assert capture == before


def test_second_box_count_metrics_survive_transport_finalization_and_saved_reports(
    capture, transports, tmp_path,
):
    client, browser = transports
    request = additional_request(capture)
    preview_request = {
        **capture, "sample_id": "SAMPLE_001",
        "vision_records": request["additional_review"]["vision_records"],
    }
    preview = client.post("/api/inspection/additional-review/preview", json=preview_request)
    assert preview.status_code == 200, preview.text
    assert browser("/api/inspection/additional-review/preview", preview_request)["body"] == preview.json()
    applied = client.post("/api/inspection/additional-review", json=request)
    assert applied.status_code == 200, applied.text
    assert applied.json() == browser("/api/inspection/additional-review", request)["body"]
    expanded = applied.json()["capture"]
    expanded.update(
        confirmed=True, inspector_name="Inspector TEST",
        final_decisions={"SAMPLE_001": "COMPLETE"},
    )
    finalized = client.post("/api/finalize", json=expanded)
    assert finalized.status_code == 200, finalized.text
    result = finalized.json()
    browser_final = browser("/api/finalize", expanded, result["report_id"])
    assert browser_final["status"] == 200
    saved = json.loads((tmp_path / result["report_id"] / "report.json").read_text("utf-8"))
    for report in (saved, browser_final["storage"]["report"]):
        sample = report["samples"][0]
        assert sample["inspection_summary"]["total_fruits"] == 297
        assert [box["actual_count"] for box in sample["box_inspections"]] == [146, 151]
        assert [box["count_difference"] for box in sample["box_inspections"]] == [-4, 1]
        assert sample["box_inspection"]["actual_count"] == 146
        assert sample["review_history"] == expanded["samples"][0]["review_history"]
    assert browser_final["storage"]["source"] == expanded
    assert json.loads((tmp_path / result["report_id"] / "source.json").read_text("utf-8")) == expanded
