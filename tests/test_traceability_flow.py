"""Traceability at import time and preservation in the completed QC report.

The source predictions are the technical Vision demo, never private QC rows.
The browser transport is invoked as Python; no browser or preview server runs.
"""

import io
import json
import runpy
from copy import deepcopy
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from smartfruit.app import create_app
from smartfruit.image_binding import validate_vision_import
from smartfruit.vision_capture import VisionCapture
from smartfruit.workflow import evaluate_inspection

ROOT = Path(__file__).resolve().parents[1]
MANUAL_DEFECTS = (
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
HUMAN_SUMMARY = {
    "label_brand": "Label summary entered by inspector",
    "packing_date": "N/A summary entered by inspector",
    "plu_coo": "PLU / COO summary entered by inspector",
    "open_rating": "Good to fair",
    "color_rating": "Fair",
}


@pytest.fixture
def original_records():
    return [
        json.loads((ROOT / "examples" / "vision" / f"IMG_{image}.json").read_text("utf-8"))
        for image in (6426, 6427, 6428)
    ]


@pytest.fixture
def import_payload(original_records):
    # No inspection date, QC counts, or coverage confirmation is required yet.
    return {
        "qc_header": {"lot_id": "LOT_DEMO_001"},
        "samples": [
            {
                "sample_id": "SAMPLE_DEMO_001",
                "pallet_id": "PALLET_DEMO_01",
                "vision_records": [],
            }
        ],
        "sample_id": "SAMPLE_DEMO_001",
        "vision_records": original_records,
    }


@pytest.fixture
def client(tmp_path):
    manager = VisionCapture(tmp_path / "vision-input", tmp_path / "vision-output")
    with TestClient(create_app(tmp_path, False, manager), raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def browser_dispatch():
    namespace = runpy.run_path(str(ROOT / "hosting" / "browser" / "browser_api.py"))

    def dispatch(path, payload):
        return json.loads(namespace["smartfruit_browser_api"]("POST", path, json.dumps(payload)))

    return dispatch


def _import(client, payload):
    response = client.post("/api/vision/import", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _capture(import_result):
    return {
        "qc_header": {
            "lot_id": "LOT_DEMO_001",
            "inspection_date": "2026-11-13",
            "Level_Flag": 1,
        },
        "samples": [
            {
                "sample_id": "SAMPLE_DEMO_001",
                "pallet_id": "PALLET_DEMO_01",
                "vision_records": import_result["vision_records"],
                "image_bindings": import_result["image_bindings"],
                "vision_covers_sample": True,
                "qc_fields": {
                    **dict.fromkeys(MANUAL_DEFECTS, 0),
                    "sample_count": 36,
                    "label_brand": "Sample label distinct from summary",
                    "packing_date": "2026-11-01",
                    "plu_coo": "Sample PLU",
                    "open_rating": "Good",
                    "color_rating": "Good",
                },
            }
        ],
    }


def test_incomplete_qc_can_import_original_json_with_external_bindings(
    client,
    browser_dispatch,
    import_payload,
    original_records,
    tmp_path,
):
    before = deepcopy(import_payload)
    result = _import(client, import_payload)
    assert result == validate_vision_import(import_payload)
    envelope = browser_dispatch("/api/vision/import", import_payload)
    assert envelope["status"] == 200
    assert envelope["body"] == result
    assert result["vision_records"] == original_records
    assert import_payload == before
    for record in result["vision_records"]:
        assert {"lot_id", "pallet_id", "sample_id"}.isdisjoint(record)
    assert result["image_bindings"] == [
        {
            "image_id": record["image_id"],
            "lot_id": "LOT_DEMO_001",
            "pallet_id": "PALLET_DEMO_01",
            "sample_id": "SAMPLE_DEMO_001",
        }
        for record in original_records
    ]
    assert result["inspection_summary"]["total_fruits"] == 36
    assert result["inspection_summary"]["oleocellosis_count"] == 3
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("missing", ["lot", "target", "sample", "pallet"])
def test_import_requires_lot_pallet_and_an_existing_named_sample(
    client,
    browser_dispatch,
    import_payload,
    missing,
):
    if missing == "lot":
        import_payload["qc_header"].pop("lot_id")
    elif missing == "target":
        import_payload["sample_id"] = "NO_SUCH_SAMPLE"
    else:
        import_payload["samples"][0].pop("sample_id" if missing == "sample" else "pallet_id")
    assert client.post("/api/vision/import", json=import_payload).status_code == 422
    assert browser_dispatch("/api/vision/import", import_payload)["status"] == 422


def test_existing_files_and_raw_duplicate_trace_are_retained_without_inflating_counts(
    client,
    browser_dispatch,
    import_payload,
    original_records,
):
    first = _import(client, import_payload)
    import_payload["samples"][0].update(
        vision_records=first["vision_records"],
        image_bindings=first["image_bindings"],
    )
    import_payload["vision_records"] = [deepcopy(original_records[0])]
    before = deepcopy(import_payload)
    result = _import(client, import_payload)
    assert browser_dispatch("/api/vision/import", import_payload)["body"] == result
    assert result["vision_records"] == original_records + [original_records[0]]
    assert len(result["vision_records"]) == 4
    assert len(result["image_bindings"]) == 3
    summary = result["inspection_summary"]
    assert summary["total_fruits"] == 36
    assert summary["oleocellosis_count"] == 3
    assert summary["images_processed"] == 3
    assert summary["duplicate_image_ids_ignored"] == ["IMG_6426"]
    assert import_payload == before


@pytest.mark.parametrize("same_pallet", [True, False])
def test_same_photo_cannot_be_imported_to_another_sample_even_on_same_pallet(
    client,
    browser_dispatch,
    import_payload,
    original_records,
    same_pallet,
):
    import_payload["samples"].append(
        {
            "sample_id": "OTHER_SAMPLE",
            "pallet_id": "PALLET_DEMO_01" if same_pallet else "OTHER_PALLET",
            "vision_records": [deepcopy(original_records[0])],
        }
    )
    before = deepcopy(import_payload)
    assert client.post("/api/vision/import", json=import_payload).status_code == 422
    assert browser_dispatch("/api/vision/import", import_payload)["status"] == 422
    with pytest.raises(ValueError):
        validate_vision_import(import_payload)
    assert import_payload == before


def test_malformed_batch_is_atomic_and_does_not_remove_existing_files(
    client,
    browser_dispatch,
    import_payload,
    original_records,
):
    import_payload["samples"][0]["vision_records"] = [deepcopy(original_records[0])]
    malformed = deepcopy(original_records[2])
    malformed["fruit_predictions"] = []
    import_payload["vision_records"] = [deepcopy(original_records[1]), malformed]
    before = deepcopy(import_payload)
    assert client.post("/api/vision/import", json=import_payload).status_code == 422
    assert browser_dispatch("/api/vision/import", import_payload)["status"] == 422
    with pytest.raises(ValueError):
        validate_vision_import(import_payload)
    assert import_payload == before
    assert import_payload["samples"][0]["vision_records"] == original_records[:1]


@pytest.mark.parametrize("changed_context", ["lot_id", "pallet_id", "sample_id"])
def test_reassigning_qc_identifiers_after_import_invalidates_bindings(
    client,
    browser_dispatch,
    import_payload,
    changed_context,
):
    capture = _capture(_import(client, import_payload))
    if changed_context == "lot_id":
        capture["qc_header"]["lot_id"] = "REASSIGNED_LOT"
    else:
        capture["samples"][0][changed_context] = "REASSIGNED_CONTEXT"
    assert client.post("/api/evaluate", json=capture).status_code == 422
    assert browser_dispatch("/api/evaluate", capture)["status"] == 422
    with pytest.raises(ValueError):
        evaluate_inspection(capture)


@pytest.mark.parametrize("invalid_binding", ["missing", "duplicate", "extra-image", "extra-field"])
def test_final_workflow_requires_exact_binding_coverage(
    client,
    browser_dispatch,
    import_payload,
    invalid_binding,
):
    capture = _capture(_import(client, import_payload))
    bindings = capture["samples"][0]["image_bindings"]
    if invalid_binding == "missing":
        bindings.pop()
    elif invalid_binding == "duplicate":
        bindings.append(deepcopy(bindings[0]))
    elif invalid_binding == "extra-image":
        bindings.append({**bindings[0], "image_id": "NO_SUCH_IMAGE"})
    else:
        bindings[0]["unexpected"] = "not part of binding contract"
    assert client.post("/api/evaluate", json=capture).status_code == 422
    assert browser_dispatch("/api/evaluate", capture)["status"] == 422


def test_bindings_and_human_qc_summary_survive_final_json_and_excel_totals(
    client,
    browser_dispatch,
    import_payload,
    tmp_path,
):
    imported = _import(client, import_payload)
    capture = _capture(imported)
    capture.update(
        qc_summary=deepcopy(HUMAN_SUMMARY),
        confirmed=True,
        inspector_name="Inspector Demo",
        final_decisions={"SAMPLE_DEMO_001": "STANDARD"},
    )
    preview = client.post("/api/evaluate", json=capture)
    assert preview.status_code == 200
    assert preview.json()["qc_summary"] == HUMAN_SUMMARY
    assert browser_dispatch("/api/evaluate", capture)["body"] == preview.json()
    finalized = client.post("/api/finalize", json=capture)
    assert finalized.status_code == 200, finalized.text
    body = finalized.json()
    report = body["report"]
    sample = report["samples"][0]
    assert sample["image_bindings"] == imported["image_bindings"]
    assert sample["final_recommendation"] == "EXPAND"
    assert sample["inspector_final_decision"] == "STANDARD"
    assert report["qc_summary"] == HUMAN_SUMMARY
    assert report["qc_header"]["Level_Flag"] == 1
    stored = tmp_path / body["report_id"]
    assert json.loads((stored / "source.json").read_text("utf-8")) == capture
    assert json.loads((stored / "report.json").read_text("utf-8")) == report
    assert client.get(body["downloads"]["json"]).json() == report
    workbook_response = client.get(body["downloads"]["xlsx"])
    assert workbook_response.status_code == 200
    sheet = openpyxl.load_workbook(io.BytesIO(workbook_response.content), data_only=True)["Report"]
    assert sheet["I16"].value == 36
    assert sheet["R16"].value == 3
    assert sheet["A16"].value == "Sample label distinct from summary"
    for column, key in {
        "A": "label_brand",
        "D": "packing_date",
        "H": "plu_coo",
        "J": "open_rating",
        "K": "color_rating",
    }.items():
        assert sheet[f"{column}17"].value == HUMAN_SUMMARY[key]


def test_optional_fields_do_not_change_legacy_capture_when_absent(client, original_records):
    capture = _capture({"vision_records": original_records, "image_bindings": []})
    del capture["samples"][0]["image_bindings"]
    response = client.post("/api/evaluate", json=capture)
    assert response.status_code == 200
    report = response.json()
    assert "qc_summary" not in report
    assert "image_bindings" not in report["samples"][0]
    assert report["samples"][0]["final_recommendation"] == "EXPAND"


@pytest.mark.parametrize("invalid", [None, True, [], "not a summary", 10])
def test_invalid_qc_summary_shape_is_a_client_error(
    client,
    browser_dispatch,
    import_payload,
    invalid,
):
    capture = _capture(_import(client, import_payload))
    capture["qc_summary"] = invalid
    assert client.post("/api/evaluate", json=capture).status_code == 422
    assert browser_dispatch("/api/evaluate", capture)["status"] == 422


@pytest.mark.parametrize("invalid_value", [True, {"bad": "shape"}, ["bad"]])
def test_invalid_summary_field_types_are_not_silently_coerced(
    client,
    browser_dispatch,
    import_payload,
    invalid_value,
):
    capture = _capture(_import(client, import_payload))
    capture["qc_summary"] = {**HUMAN_SUMMARY, "open_rating": invalid_value}
    assert client.post("/api/evaluate", json=capture).status_code == 422
    assert browser_dispatch("/api/evaluate", capture)["status"] == 422


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_summary_values_are_rejected_by_both_transports(
    client,
    browser_dispatch,
    import_payload,
    invalid_value,
):
    capture = _capture(_import(client, import_payload))
    capture["qc_summary"] = {**HUMAN_SUMMARY, "open_rating": invalid_value}
    response = client.post(
        "/api/evaluate",
        content=json.dumps(capture),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert browser_dispatch("/api/evaluate", capture)["status"] == 422
    with pytest.raises(ValueError):
        evaluate_inspection(capture)


@pytest.mark.parametrize("name", ["drafts.js", "field_sources.js"])
def test_client_assets_are_served_as_javascript(client, name):
    response = client.get(f"/assets/{name}")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.text == (ROOT / "src" / "smartfruit" / "web" / name).read_text("utf-8")
    assert response.text.strip()


@pytest.mark.parametrize("name", ["unknown.js", "app.py", "index.html"])
def test_unlisted_assets_are_not_found(client, name):
    assert client.get(f"/assets/{name}").status_code == 404
