"""Lot reception, per-pallet Vision and printable reports use the same capture."""

import io
import json
import runpy
import shutil
import subprocess
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from smartfruit.app import create_app
from smartfruit.image_binding import validate_vision_import
from smartfruit.inspection import MANUAL_DEFECTS
from smartfruit.print_report import render_qc_print
from smartfruit.reception import load_reception_manifest, resolve_reception_lot
from smartfruit.vision_capture import VisionCapture
from smartfruit.workflow import evaluate_inspection

ROOT = Path(__file__).resolve().parents[1]
CSV = (
    "scan_code,lot_id,label_brand,country_origin,pallet_id,size_declared,expected_count_per_box,grower,packing_date\n"
    "TEST-P1,TEST-LOT,TEST-LABEL,Mexico,P1,42,42,TEST-GROWER,2026-11-01\n"
    "TEST-P2,TEST-LOT,TEST-LABEL,Mexico,P2,48,48,TEST-GROWER,2026-11-02\n"
    "TEST-OTHER,OTHER-LOT,TEST-LABEL,Mexico,P3,54,54,OTHER-GROWER,2026-11-03\n"
)


@pytest.fixture
def capture():
    lot = resolve_reception_lot(load_reception_manifest(CSV), "P1")
    samples = []
    for index, pallet in enumerate(lot["pallets"]):
        record = json.loads((ROOT / f"examples/vision/IMG_{6426 + index}.json").read_text())
        samples.append(
            {
                "sample_id": f"TEST-SAMPLE-{index}",
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
    samples[1]["qc_fields"]["scars"] = 2
    return {
        "qc_header": {**lot["qc_header"], "inspection_date": "2026-11-14", "Level_Flag": 1},
        "lot_reception": {"scan_input": "P1", "records": lot["records"]},
        "samples": samples,
    }


def browser(path, payload):
    dispatch = runpy.run_path(str(ROOT / "hosting/browser/browser_api.py"))[
        "smartfruit_browser_api"
    ]
    return json.loads(dispatch("POST", path, json.dumps(payload)))


def test_scan_discovers_complete_lot_and_prefills_existing_reception_fields(tmp_path):
    with TestClient(create_app(tmp_path, False)) as client:
        response = client.post("/api/reception/lot", json={"manifest_csv": CSV, "scan_input": "P1"})
    assert response.status_code == 200
    lot = response.json()
    assert lot == browser("/api/reception/lot", {"manifest_csv": CSV, "scan_input": "P1"})["body"]
    assert lot["lot_id"] == "TEST-LOT"
    assert [p["pallet_id"] for p in lot["pallets"]] == ["P1", "P2"]
    assert lot["pallets"][0]["qc_fields"]["grower"] == "TEST-GROWER"
    assert "sample_count" not in lot["pallets"][0]["qc_fields"]
    assert "avg_count_per_box" not in lot["pallets"][0]["qc_fields"]


@pytest.mark.parametrize("source", ["synthetic", "demo-manifest"])
@pytest.mark.parametrize("mode", ["scan", "lot"])
def test_frontend_accepts_lot_api_response_and_opens_every_pallet(tmp_path, source, mode):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to execute the reception interface")
    manifest, scan = CSV, "P1"
    if source == "demo-manifest":
        path = ROOT / "examples/reception/SmartFruit_reception_manifest_demo.csv"
        manifest, scan = path.read_text(encoding="utf-8-sig"), "5645"
    payload = {"manifest_csv": manifest}
    if mode == "scan":
        payload["scan_input"] = scan
    else:
        payload["lot_id"] = resolve_reception_lot(load_reception_manifest(manifest), scan)["lot_id"]
    with TestClient(create_app(tmp_path, False)) as client:
        response = client.post("/api/reception/lot", json=payload)
    assert response.status_code == 200
    local = response.json()
    hosted = browser("/api/reception/lot", payload)
    assert hosted["status"] == 200 and hosted["body"] == local
    assert "pallet_id" not in local  # The lot contract uses scanned_pallet_id.
    if source == "demo-manifest":
        assert local["lot_id"] == "5815" and len(local["pallets"]) == 7
    result = subprocess.run(
        [node, str(ROOT / "tests/helpers/reception_selection.cjs")],
        input=json.dumps([local, hosted["body"]]),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_assigns_different_original_images_to_different_pallets(capture):
    original = deepcopy(capture)
    for sample in capture["samples"]:
        result = validate_vision_import(
            {**capture, "sample_id": sample["sample_id"], "vision_records": []}
        )
        sample["image_bindings"] = result["image_bindings"]
    report = evaluate_inspection(capture)
    assert [s["image_bindings"][0]["pallet_id"] for s in report["samples"]] == ["P1", "P2"]
    assert all(
        s["vision_records"] == old["vision_records"]
        for s, old in zip(capture["samples"], original["samples"])
    )
    assert report["lot_summary"]["pallet_count"] == 2
    assert report["lot_summary"]["sample_count"] == 24
    scars = next(d for d in report["lot_summary"]["defects"] if d["key"] == "scars")
    assert scars["count"] == 2 and scars["pct"] == pytest.approx(100 * 2 / 24)
    assert "Scars" in report["generated_reason"]
    assert report["qc_header"]["Level_Flag"] == 1
    assert report["lot_summary"]["level_flag_status"] == "INSPECTOR_REQUIRED"


@pytest.mark.parametrize("problem", ["missing", "duplicate", "other", "receipt", "other_lot"])
def test_lot_roster_cannot_lose_or_mix_pallets_at_import_or_evaluation(capture, problem):
    if problem == "missing":
        capture["samples"].pop()
    elif problem == "duplicate":
        capture["samples"].append(deepcopy(capture["samples"][0]))
    elif problem == "other":
        capture["samples"][0]["pallet_id"] = "P3"
    elif problem == "receipt":
        capture["samples"][0]["reception"]["records"][0]["grower"] = "CHANGED"
    else:
        capture["lot_reception"]["records"].append(load_reception_manifest(CSV)[2])
    before = deepcopy(capture)
    with pytest.raises(ValueError):
        evaluate_inspection(capture)
    with pytest.raises(ValueError):
        validate_vision_import(
            {**capture, "sample_id": capture["samples"][0]["sample_id"], "vision_records": []}
        )
    assert capture == before


def test_print_draft_never_confirms_and_saved_print_retains_actual_decisions(capture, tmp_path):
    capture["qc_header"].update(remarks='<script>alert("QC")</script>', reason="See below")
    manager = VisionCapture(tmp_path / "vision-input", tmp_path / "vision-output")
    with TestClient(create_app(tmp_path, False, manager)) as client:
        draft = client.post("/api/report/print", json=capture)
        assert draft.status_code == 200 and draft.headers["content-type"].startswith("text/html")
        assert "BORRADOR" in draft.text and '<script>alert("QC")</script>' not in draft.text
        assert "&lt;script&gt;" in draft.text and "window.print()" in draft.text
        assert browser("/api/report/print", capture)["body"] == draft.text
        assert list(tmp_path.iterdir()) == []
        payload = {
            **capture,
            "confirmed": True,
            "inspector_name": "Inspector TEST",
            "final_decisions": {sample["sample_id"]: "STANDARD" for sample in capture["samples"]},
        }
        final = client.post("/api/finalize", json=payload)
        assert final.status_code == 200
        saved = final.json()
        printable = client.get(saved["downloads"]["print"])
        assert printable.status_code == 200
        assert "CONFIRMADO" in printable.text and "Inspector TEST" in printable.text
        assert "STANDARD" in printable.text and "predicted_loss_pct" not in printable.text
        stored = client.get(saved["downloads"]["json"]).json()
        assert stored["lot_reception"] == capture["lot_reception"]
        workbook = openpyxl.load_workbook(
            io.BytesIO(client.get(saved["downloads"]["xlsx"]).content)
        )
        assert [workbook["Report"][f"B{row}"].value for row in (16, 17)] == ["P1", "P2"]
        assert (
            client.get("/api/reports/00000000-0000-4000-8000-000000000001/print").status_code == 404
        )


def test_print_preserves_columns_logo_and_escapes_every_entered_text(capture):
    capture["samples"][0]["qc_fields"]["grower"] = '<img src=x onerror="alert(1)">'
    report = evaluate_inspection(capture)
    html = render_qc_print(report)
    assert "data:image/png;base64," in html
    assert "<img src=x" not in html and "&lt;img src=x" in html
    assert "Total Percent Combined" in html and "General Information" in html
    assert "@page { size: A3 landscape;" in html
    assert 'src="http' not in html and 'href="http' not in html

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows = 0

        def handle_starttag(self, tag, attrs):
            if tag == "tr" and ("class", "qc-data") in attrs:
                self.rows += 1

    parsed = Parser()
    parsed.feed(html)
    assert parsed.rows == 2


def test_new_lot_confirmation_requires_inspector_level_flag(capture, tmp_path):
    capture["qc_header"]["Level_Flag"] = ""
    capture.update(
        confirmed=True,
        inspector_name="Inspector TEST",
        final_decisions={s["sample_id"]: "STANDARD" for s in capture["samples"]},
    )
    with TestClient(create_app(tmp_path, False)) as client:
        response = client.post("/api/finalize", json=capture)
    assert response.status_code == 422 and "Level Flag" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []
