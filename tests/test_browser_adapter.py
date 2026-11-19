"""The browser transport must preserve the existing workflow and QC output."""

import base64
import importlib.util
import json
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import openpyxl
from review_helpers import confirm_vision_records

from smartfruit.workflow import evaluate_inspection

spec = importlib.util.spec_from_file_location(
    "browser_api", Path(__file__).resolve().parents[1] / "hosting/browser/browser_api.py"
)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def call(path, payload=None, report_id=""):
    return json.loads(
        adapter.smartfruit_browser_api(
            "GET" if payload is None else "POST",
            path,
            "" if payload is None else json.dumps(payload),
            report_id,
        )
    )


def capture():
    demo = call("/api/demo")["body"]
    config = call("/api/config")["body"]
    return {
        "qc_header": demo["qc_header"],
        "samples": [
            {
                "sample_id": demo["sample_id"],
                "pallet_id": demo["pallet_id"],
                "vision_records": confirm_vision_records(demo["records"]),
                "vision_covers_sample": True,
                "qc_fields": {field["key"]: 0 for field in config["manual_defects"]},
            }
        ],
    }


def test_browser_transport_preserves_the_python_workflow():
    payload = capture()
    result = call("/api/evaluate", payload)
    assert result["status"] == 200
    assert result["body"] == evaluate_inspection(payload, use_predictive=False)
    assert result["body"]["samples"][0]["final_recommendation"] == "EXTEND"


def test_browser_draft_uses_the_same_qc_format():
    response = call("/api/export", capture())
    assert response["status"] == 200
    sheet = openpyxl.load_workbook(BytesIO(base64.b64decode(response["body"])), data_only=True)[
        "Report"
    ]
    assert sheet["I16"].value == 36
    assert sheet["R16"].value == 3
    text = " ".join(str(cell.value) for row in sheet for cell in row)
    assert "BORRADOR" in text and "predicted_loss_pct" not in text


def test_browser_confirmation_preserves_inspector_authority_and_capture():
    payload = capture()
    payload.update(
        inspector_name="Inspector DEMO",
        confirmed=True,
        final_decisions={"SAMPLE_DEMO_001": "STANDARD"},
    )
    report_id = str(uuid4())
    result = call("/api/finalize", payload, report_id)
    assert result["status"] == 200
    assert result["storage"]["source"] == payload
    assert result["storage"]["id"] == report_id
    report = result["storage"]["report"]
    assert report["samples"][0]["final_recommendation"] == "EXTEND"
    assert report["samples"][0]["inspector_final_decision"] == "STANDARD"
    assert report["inspector_confirmed"] is True
    assert "predicted_loss_pct" not in report["samples"][0]["predictive"]


def test_browser_transport_rejects_missing_manual_data_and_confirmation():
    payload = capture()
    payload["samples"][0]["qc_fields"].pop("mold")
    assert call("/api/evaluate", payload)["status"] == 422
    result = call("/api/finalize", capture(), str(uuid4()))
    assert result["status"] == 422
    assert "storage" not in result
