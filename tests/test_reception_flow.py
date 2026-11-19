"""CSV reception → exact scan selection → QC, without inventing measurements.

CSV fixtures are generated here from the existing field names. They contain no
operational manifest rows and only deliberately pair the synthetic identifiers
with the three Vision demo JSONs.
"""

import csv
import io
import json
import runpy
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import openpyxl
import pytest
from fastapi.testclient import TestClient
from review_helpers import confirm_vision_records

from smartfruit.app import create_app
from smartfruit.reception import load_reception_manifest, manifest_summary, resolve_reception
from smartfruit.vision_capture import VisionCapture
from smartfruit.workflow import evaluate_inspection

ROOT = Path(__file__).resolve().parents[1]
CSV_FIELDS = (
    "demo_case_id",
    "shipment_id",
    "scan_code",
    "scan_level",
    "lot_id",
    "label_brand",
    "country_origin",
    "pallet_id",
    "packing_date",
    "size_declared",
    "expected_count_per_box",
    "qty_received_weight",
    "boxes_received",
    "data_origin",
    "source_record",
    "status",
)
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


def _csv(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    return "\ufeff" + output.getvalue()


@pytest.fixture
def source_rows():
    selected = dict.fromkeys(CSV_FIELDS, "")
    selected.update(
        demo_case_id="SYNTHETIC_CASE_01",
        shipment_id="SYNTHETIC_SHIPMENT_01",
        scan_code="SYNTHETIC_SCAN_01",
        scan_level="PALLET",
        lot_id="LOT_DEMO_001",
        label_brand="Marca de prueba",
        country_origin="País de prueba",
        pallet_id="PALLET_DEMO_01",
        packing_date="2026-11-13",
        size_declared="110",
        expected_count_per_box="110",
        data_origin="SYNTHETIC_TEST",
        source_record="synthetic-reception-fixture",
        status="READY",
    )
    unrelated = deepcopy(selected)
    unrelated.update(
        demo_case_id="SYNTHETIC_CASE_02",
        lot_id="OTHER_TEST_LOT",
        pallet_id="OTHER_TEST_PALLET",
        scan_code="OTHER_TEST_SCAN",
        source_record="UNRELATED_RECORD_MUST_NOT_BE_PERSISTED",
    )
    return [selected, unrelated]


@pytest.fixture
def client(tmp_path):
    manager = VisionCapture(tmp_path / "vision-input", tmp_path / "vision-output")
    with TestClient(create_app(tmp_path, False, manager), raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def browser_api():
    # Load the transport adapter directly; this starts neither browser nor server.
    namespace = runpy.run_path(str(ROOT / "hosting" / "browser" / "browser_api.py"))

    def dispatch(path, payload):
        return json.loads(namespace["smartfruit_browser_api"]("POST", path, json.dumps(payload)))

    return dispatch


def _selection(client, rows, scan="SYNTHETIC_SCAN_01"):
    response = client.post(
        "/api/reception/resolve",
        json={"manifest_csv": _csv(rows), "scan_input": scan},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _capture(selection):
    records = [
        json.loads((ROOT / "examples" / "vision" / f"IMG_{image}.json").read_text("utf-8"))
        for image in (6426, 6427, 6428)
    ]
    return {
        "qc_header": {**selection["qc_header"], "inspection_date": "2026-11-13", "Level_Flag": 1},
        "samples": [
            {
                "sample_id": "RECEPTION_FLOW_SAMPLE",
                "pallet_id": selection["pallet_id"],
                "vision_records": confirm_vision_records(records),
                "vision_covers_sample": True,
                "qc_fields": {
                    **selection["qc_fields"],
                    **dict.fromkeys(MANUAL_DEFECTS, 0),
                    "sample_count": 36,
                },
                "reception": {
                    "scan_input": selection["scan_input"],
                    "records": selection["records"],
                },
            }
        ],
    }


def test_import_returns_raw_rows_and_summary_identical_to_core_and_browser(
    client,
    browser_api,
    source_rows,
):
    payload = {"manifest_csv": _csv(source_rows)}
    response = client.post("/api/reception/manifest", json=payload)
    assert response.status_code == 200
    imported = response.json()
    assert imported == manifest_summary(load_reception_manifest(payload["manifest_csv"]))
    assert imported["records"] == source_rows
    assert imported["pallets_count"] == 2
    assert imported["lot_ids"] == ["LOT_DEMO_001", "OTHER_TEST_LOT"]
    assert imported["records"][0]["boxes_received"] == ""
    assert imported["records"][0]["qty_received_weight"] == ""
    envelope = browser_api("/api/reception/manifest", payload)
    assert envelope["status"] == 200
    assert envelope["body"] == imported


@pytest.mark.parametrize("scan", ["SYNTHETIC_SCAN_01", "PALLET_DEMO_01"])
def test_scan_prepopulates_metadata_without_treating_declared_count_as_measured_sample(
    client,
    browser_api,
    source_rows,
    scan,
):
    selection = _selection(client, source_rows, scan)
    payload = {"manifest_csv": _csv(source_rows), "scan_input": scan}
    assert selection == resolve_reception(source_rows, scan)
    assert browser_api("/api/reception/resolve", payload)["body"] == selection
    assert selection["records"] == source_rows[:1]
    assert selection["qc_header"]["lot_id"] == "LOT_DEMO_001"
    assert selection["qc_header"]["country_origin"] == "País de prueba"
    assert selection["qc_fields"] == {
        "pallet_id": "PALLET_DEMO_01",
        "label_brand": "Marca de prueba",
        "packing_date": "2026-11-13",
        "size": "110",
    }
    assert "sample_count" not in selection["qc_fields"]
    assert "avg_count_per_box" not in selection["qc_fields"]
    assert "oleocellosis" not in selection["qc_fields"]

    capture = _capture(selection)
    response = client.post("/api/evaluate", json=capture)
    assert response.status_code == 200
    report = response.json()
    assert report == evaluate_inspection(capture)
    assert browser_api("/api/evaluate", capture)["body"] == report
    sample = report["samples"][0]
    assert sample["qc_fields"]["sample_count"] == 36
    assert sample["qc_fields"]["oleocellosis"] == 3
    assert sample["qc_fields"]["avg_count_per_box"] == ""
    assert sample["inspection_summary"]["oleocellosis_pct"] == pytest.approx(100 * 3 / 36)
    assert sample["business_severity"]["business_max_level"] == 2
    assert sample["final_recommendation"] == "EXTEND"
    assert sample["reception"]["records"][0]["expected_count_per_box"] == "110"
    assert sample["reception"]["records"][0]["boxes_received"] == ""
    assert sample["reception"] == capture["samples"][0]["reception"]


def test_mixed_size_pallet_keeps_both_rows_and_does_not_choose_a_size(client, source_rows):
    extra_size = deepcopy(source_rows[0])
    extra_size.update(
        scan_code="SYNTHETIC_SIZE_175", size_declared="175", expected_count_per_box="175"
    )
    rows = [source_rows[0], extra_size, source_rows[1]]
    selection = _selection(client, rows)
    assert selection["records"] == [source_rows[0], extra_size]
    assert selection["qc_fields"]["size"] == ""
    assert "avg_count_per_box" not in selection["qc_fields"]
    report = evaluate_inspection(_capture(selection))
    sample = report["samples"][0]
    assert sample["qc_fields"]["size"] == ""
    assert sample["inspection_summary"]["total_fruits"] == 36
    assert [row["size_declared"] for row in sample["reception"]["records"]] == ["110", "175"]
    assert sample["final_recommendation"] == "EXTEND"


@pytest.mark.parametrize("case", ["wrong-lot", "wrong-pallet", "extra-entity"])
def test_capture_rejects_mismatched_or_unfiltered_reception(
    client,
    browser_api,
    source_rows,
    case,
):
    capture = _capture(_selection(client, source_rows))
    if case == "wrong-lot":
        capture["qc_header"]["lot_id"] = "UNRELATED_LOT"
    elif case == "wrong-pallet":
        capture["samples"][0]["pallet_id"] = "UNRELATED_PALLET"
        capture["samples"][0]["qc_fields"]["pallet_id"] = "UNRELATED_PALLET"
    else:
        capture["samples"][0]["reception"]["records"] = source_rows
    response = client.post("/api/evaluate", json=capture)
    assert response.status_code == 422, response.text
    assert browser_api("/api/evaluate", capture)["status"] == 422
    with pytest.raises(ValueError):
        evaluate_inspection(capture)


@pytest.mark.parametrize("endpoint", ["manifest", "resolve"])
def test_string_path_is_rejected_as_csv_and_never_opened(
    client,
    browser_api,
    monkeypatch,
    endpoint,
):
    # A string from HTTP is CSV text. Local paths require an explicit PathLike
    # in the core API, which cannot be supplied through this JSON contract.
    path_constructor = Mock(side_effect=AssertionError("HTTP text must never open a local path"))
    monkeypatch.setattr("smartfruit.reception.Path", path_constructor)
    payload = {"manifest_csv": "/etc/passwd", "scan_input": "PALLET_DEMO_01"}
    response = client.post(f"/api/reception/{endpoint}", json=payload)
    assert response.status_code == 422
    assert browser_api(f"/api/reception/{endpoint}", payload)["status"] == 422
    path_constructor.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"manifest_csv": None},
        {"manifest_csv": []},
        {"manifest_csv": "not a manifest"},
    ],
)
def test_reception_routes_reject_invalid_payloads_consistently(client, browser_api, payload):
    for endpoint in ("manifest", "resolve"):
        path = f"/api/reception/{endpoint}"
        assert client.post(path, json=payload).status_code == 422
        assert browser_api(path, payload)["status"] == 422


def test_finalize_preserves_only_selected_provenance_and_inspector_decision(
    client,
    browser_api,
    source_rows,
    tmp_path,
):
    selection = _selection(client, source_rows)
    capture = _capture(selection)
    # Vision's contract has no commercial identifiers: the selected reception
    # and sample provide them outside the unchanged model output.
    for image in capture["samples"][0]["vision_records"]:
        assert not {"lot_id", "pallet_id", "sample_id"}.intersection(image)
    capture.update(
        inspector_name="Inspector de prueba",
        confirmed=True,
        final_decisions={"RECEPTION_FLOW_SAMPLE": "STANDARD"},
    )
    response = client.post("/api/finalize", json=capture)
    assert response.status_code == 200, response.text
    finalized = response.json()
    directory = tmp_path / finalized["report_id"]
    saved_source = json.loads((directory / "source.json").read_text("utf-8"))
    saved_report = json.loads((directory / "report.json").read_text("utf-8"))
    assert saved_source == capture
    assert saved_report == finalized["report"]
    assert "manifest_csv" not in saved_source
    for document in (saved_source, saved_report):
        assert document["samples"][0]["reception"] == {
            "scan_input": "SYNTHETIC_SCAN_01",
            "records": source_rows[:1],
        }
        assert "UNRELATED_RECORD_MUST_NOT_BE_PERSISTED" not in json.dumps(document)
    sample = saved_report["samples"][0]
    assert sample["final_recommendation"] == "EXTEND"
    assert sample["inspector_final_decision"] == "STANDARD"
    assert saved_report["qc_header"]["Level_Flag"] == 1
    assert sample["reception"]["records"][0]["boxes_received"] == ""
    assert client.get(finalized["downloads"]["json"]).json() == saved_report

    workbook_response = client.get(finalized["downloads"]["xlsx"])
    assert workbook_response.status_code == 200
    sheet = openpyxl.load_workbook(io.BytesIO(workbook_response.content), data_only=True)["Report"]
    assert sheet["L8"].value == selection["lot_id"]
    assert sheet["B16"].value == selection["pallet_id"]
    assert sheet["A16"].value == selection["qc_fields"]["label_brand"]
    assert sheet["E16"].value == selection["qc_fields"]["size"]
    assert sheet["I16"].value == 36
    assert sheet["R16"].value == 3
    assert sheet["F16"].value is None  # Unknown actual average stays empty.
    values = [str(cell.value) for row in sheet for cell in row if cell.value is not None]
    text = "\n".join(values)
    assert "Recepción" in text
    assert "SYNTHETIC_SCAN_01" in text
    assert "synthetic-reception-fixture" in text
    assert "UNRELATED_RECORD_MUST_NOT_BE_PERSISTED" not in text
    assert "No registrado" in text
    assert "110" in values  # Declared count, distinct from QC Sample=36.

    # The browser transport must persist the same selected source/provenance,
    # without depending on an actual browser or IndexedDB during this unit test.
    namespace = runpy.run_path(str(ROOT / "hosting" / "browser" / "browser_api.py"))
    browser_result = json.loads(
        namespace["smartfruit_browser_api"](
            "POST",
            "/api/finalize",
            json.dumps(capture),
            finalized["report_id"],
        )
    )
    assert browser_result["status"] == 200
    assert browser_result["storage"]["source"] == capture
    browser_sample = browser_result["storage"]["report"]["samples"][0]
    assert browser_sample["reception"] == sample["reception"]
    assert browser_sample["final_recommendation"] == "EXTEND"
    assert browser_sample["inspector_final_decision"] == "STANDARD"
