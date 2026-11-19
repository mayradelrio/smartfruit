"""Opening a lot directly preserves its roster through import and evaluation."""

import json
import runpy
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smartfruit.app import create_app
from smartfruit.image_binding import validate_vision_import
from smartfruit.inspection import MANUAL_DEFECTS
from smartfruit.lot_inspection import validate_lot_reception
from smartfruit.reception import load_reception_manifest, resolve_reception_lot
from smartfruit.vision_capture import VisionCapture
from smartfruit.workflow import evaluate_inspection

ROOT = Path(__file__).resolve().parents[1]
CSV = (
    "scan_code,lot_id,label_brand,country_origin,pallet_id,size_declared,expected_count_per_box\n"
    "TEST-P1,5815,TEST-LABEL,Mexico,P1,42,42\n"
    "TEST-P2,5815,TEST-LABEL,Mexico,P2,48,48\n"
    "TEST-P3,OTHER,TEST-OTHER-LABEL,Mexico,P3,54,54\n"
)


def browser(path, payload):
    dispatch = runpy.run_path(str(ROOT / "hosting/browser/browser_api.py"))[
        "smartfruit_browser_api"
    ]
    return json.loads(dispatch("POST", path, json.dumps(payload)))


@pytest.fixture
def capture():
    lot = resolve_reception_lot(load_reception_manifest(CSV), lot_id="5815")
    samples = []
    for index, pallet in enumerate(lot["pallets"]):
        record = json.loads((ROOT / f"examples/vision/IMG_{6426 + index}.json").read_text())
        samples.append(
            {
                "sample_id": f"TEST-{index}",
                "pallet_id": pallet["pallet_id"],
                "vision_records": [record],
                "vision_covers_sample": True,
                "qc_fields": {
                    **pallet["qc_fields"],
                    **{field["key"]: 0 for field in MANUAL_DEFECTS},
                },
                "reception": {"scan_input": pallet["scan_input"], "records": pallet["records"]},
            }
        )
    return {
        "qc_header": {**lot["qc_header"], "inspection_date": "2026-11-14", "Level_Flag": 1},
        "lot_reception": {"lot_id": lot["lot_id"], "records": lot["records"]},
        "samples": samples,
    }


def test_lot_endpoint_accepts_explicit_lot_without_scan_in_both_transports(tmp_path):
    payload = {"manifest_csv": CSV, "lot_id": "5815"}
    with TestClient(create_app(tmp_path, False)) as client:
        response = client.post("/api/reception/lot", json=payload)
        pallet_only = client.post("/api/reception/resolve", json=payload)
    hosted = browser("/api/reception/lot", payload)
    assert response.status_code == hosted["status"] == 200
    selected = response.json()
    assert selected == hosted["body"]
    assert selected["selection_mode"] == "lot"
    assert selected["scanned_pallet_id"] is None and "scan_input" not in selected
    assert selected["lot_id"] == "5815"
    assert [pallet["pallet_id"] for pallet in selected["pallets"]] == ["P1", "P2"]
    assert all(pallet["qc_fields"]["label_brand"] == "TEST-LABEL" for pallet in selected["pallets"])
    assert pallet_only.status_code == 422  # The single-pallet scan contract stays explicit.


def test_direct_lot_provenance_survives_vision_import_and_evaluation(capture, tmp_path):
    original = deepcopy(capture)
    payload = {**capture, "sample_id": "TEST-0", "vision_records": []}
    imported = validate_vision_import(payload)
    assert imported["vision_records"] == capture["samples"][0]["vision_records"]
    report = evaluate_inspection(capture)
    assert report["lot_reception"] == capture["lot_reception"]
    assert "scan_input" not in report["lot_reception"]
    manager = VisionCapture(tmp_path / "vision-input", tmp_path / "vision-output")
    with TestClient(create_app(tmp_path, False, manager)) as client:
        response = client.post("/api/evaluate", json=capture)
        vision = client.post("/api/vision/import", json=payload)
    assert response.status_code == vision.status_code == 200
    assert response.json() == browser("/api/evaluate", capture)["body"]
    assert vision.json() == browser("/api/vision/import", payload)["body"]
    assert capture == original


def test_direct_lot_can_be_confirmed_with_prefilled_label_and_printed_title(capture, tmp_path):
    payload = deepcopy(capture)
    payload.update(
        confirmed=True,
        inspector_name="Inspector TEST",
        final_decisions={sample["sample_id"]: "STANDARD" for sample in capture["samples"]},
    )
    with TestClient(create_app(tmp_path, False)) as client:
        response = client.post("/api/finalize", json=payload)
        assert response.status_code == 200, response.text
        downloads = response.json()["downloads"]
        saved = client.get(downloads["json"]).json()
        printable = client.get(downloads["print"])
    assert saved["lot_reception"] == capture["lot_reception"]
    assert [sample["qc_fields"]["label_brand"] for sample in saved["samples"]] == [
        "TEST-LABEL", "TEST-LABEL"
    ]
    assert printable.status_code == 200
    assert '<h1 class="inspection-title">QUALITY INSPECTION</h1>' in printable.text
    assert "TEST-LABEL" in printable.text and "CONFIRMADO" in printable.text


@pytest.mark.parametrize("problem", ["lot", "missing", "duplicate", "receipt", "foreign_row"])
def test_direct_lot_selection_still_protects_complete_roster(capture, problem):
    if problem == "lot":
        capture["lot_reception"]["lot_id"] = "OTHER"
    elif problem == "missing":
        capture["samples"].pop()
    elif problem == "duplicate":
        capture["samples"].append(deepcopy(capture["samples"][0]))
    elif problem == "receipt":
        capture["samples"][0]["reception"]["records"][0]["label_brand"] = "CHANGED"
    else:
        capture["lot_reception"]["records"].append(load_reception_manifest(CSV)[2])
    original = deepcopy(capture)
    with pytest.raises(ValueError):
        evaluate_inspection(capture)
    with pytest.raises(ValueError):
        validate_vision_import({**capture, "sample_id": "TEST-0", "vision_records": []})
    assert capture == original


def test_scan_provenance_stays_compatible_and_explicit_lot_cannot_conflict(capture):
    selected = capture["lot_reception"]
    scanned = {"scan_input": " TEST-P1 ", "records": selected["records"]}
    validated = validate_lot_reception(scanned, capture["samples"], "5815")
    assert validated == {"scan_input": "TEST-P1", "records": selected["records"]}
    with pytest.raises(ValueError):
        validate_lot_reception({**scanned, "lot_id": "OTHER"}, capture["samples"], "5815")
    with pytest.raises(ValueError):
        validate_lot_reception({"records": selected["records"]}, capture["samples"], "5815")
