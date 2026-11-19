"""Reason follows observed defects while the inspector retains the final decision."""

import base64
import io
import json
import runpy
from copy import deepcopy
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from smartfruit.app import create_app
from smartfruit.decision import confirm_inspection
from smartfruit.inspection import MANUAL_DEFECTS
from smartfruit.vision_capture import VisionCapture
from smartfruit.workflow import evaluate_inspection

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def capture():
    records = [
        json.loads((ROOT / f"examples/vision/IMG_{image}.json").read_text("utf-8"))
        for image in (6426, 6427, 6428)
    ]
    return {
        "reason_source": "defect_summary",
        "qc_header": {
            "inspection_date": "2026-11-14",
            "lot_id": "LOT_TEST",
            "Level_Flag": "",
            "reason": "Stale reason from an earlier capture",
            "remarks": "Inspector observations remain intact.",
        },
        "samples": [{
            "sample_id": "SAMPLE_TEST",
            "pallet_id": "PALLET_TEST",
            "vision_records": records,
            "vision_covers_sample": True,
            "qc_fields": {
                **{field["key"]: 0 for field in MANUAL_DEFECTS},
                "sample_count": 36,
                "label_brand": "TEST-LABEL",
                "scars": 2,
            },
        }],
    }


def browser(path, payload, report_id=""):
    dispatch = runpy.run_path(str(ROOT / "hosting/browser/browser_api.py"))[
        "smartfruit_browser_api"
    ]
    return json.loads(dispatch("POST", path, json.dumps(payload), report_id))


def test_summary_reason_is_recomputed_from_counts_without_assigning_inspector_level(capture):
    original = deepcopy(capture)
    capture["generated_reason"] = "Untrusted client summary"
    first = evaluate_inspection(capture)
    assert first["reason_source"] == "defect_summary"
    assert first["qc_header"]["reason"] == first["generated_reason"]
    assert "Scars" in first["generated_reason"] and "Oleocellosis" in first["generated_reason"]
    assert "Untrusted client summary" not in first["generated_reason"]
    assert first["qc_header"]["Level_Flag"] == ""
    assert first["qc_header"]["remarks"] == original["qc_header"]["remarks"]
    assert first["samples"][0]["inspector_final_decision"] is None
    assert first["samples"][0]["final_recommendation"] == "EXPAND"
    capture["samples"][0]["qc_fields"]["scars"] = 4
    second = evaluate_inspection(capture)
    assert second["qc_header"]["reason"] == second["generated_reason"]
    assert second["qc_header"]["reason"] != first["qc_header"]["reason"]
    assert "Total 4 / 36" in second["qc_header"]["reason"]
    assert capture["qc_header"] == original["qc_header"]


@pytest.mark.parametrize("source", ["inspector", None])
def test_reviewed_and_legacy_reasons_are_preserved_separately_from_summary(capture, source):
    if source is None:
        capture.pop("reason_source")
        capture["qc_header"]["reason"] = "See below"
    else:
        capture["reason_source"] = source
        capture["qc_header"]["reason"] = "Inspector reviewed wording about the observed defects."
    original = deepcopy(capture)
    report = evaluate_inspection(capture)
    assert report["qc_header"]["reason"] == capture["qc_header"]["reason"]
    assert report["generated_reason"] != report["qc_header"]["reason"]
    assert ("reason_source" in report) == (source is not None)
    assert report["qc_header"]["remarks"] == capture["qc_header"]["remarks"]
    assert capture == original


@pytest.mark.parametrize("source", [None, "", "summary", True, 1, [], {}])
def test_invalid_reason_source_is_rejected_without_mutating_capture(capture, source):
    capture["reason_source"] = source
    original = deepcopy(capture)
    with pytest.raises(ValueError, match="reason_source"):
        evaluate_inspection(capture)
    assert capture == original


def test_inspector_can_decide_after_suggestion_without_overwriting_system_result(capture):
    evaluated = evaluate_inspection(capture)
    assert evaluated["samples"][0]["final_recommendation"] == "EXPAND"
    capture["qc_header"]["Level_Flag"] = 1
    reviewed = evaluate_inspection(capture)
    confirmed = confirm_inspection(reviewed, "Inspector TEST", {"SAMPLE_TEST": "STANDARD"}, True)
    assert confirmed["qc_header"]["Level_Flag"] == 1
    assert confirmed["samples"][0]["final_recommendation"] == "EXPAND"
    assert confirmed["samples"][0]["inspector_final_decision"] == "STANDARD"
    assert confirmed["qc_header"]["reason"] == confirmed["generated_reason"]
    assert evaluated["qc_header"]["Level_Flag"] == ""
    assert evaluated["inspector_confirmed"] is False


def test_both_transports_export_and_confirm_the_current_summary_reason(capture, tmp_path):
    payload = deepcopy(capture)
    payload["qc_header"]["Level_Flag"] = 1
    payload.update(
        inspector_name="Inspector TEST", confirmed=True,
        final_decisions={"SAMPLE_TEST": "STANDARD"},
    )
    manager = VisionCapture(tmp_path / "vision-input", tmp_path / "vision-output")
    with TestClient(create_app(tmp_path, False, manager)) as client:
        evaluated = client.post("/api/evaluate", json=capture)
        hosted = browser("/api/evaluate", capture)
        assert evaluated.status_code == hosted["status"] == 200
        assert evaluated.json() == hosted["body"]
        expected = evaluated.json()["generated_reason"]
        exported = client.post("/api/export", json=capture)
        assert exported.status_code == 200
        book = openpyxl.load_workbook(io.BytesIO(exported.content))
        assert book["Report"]["X2"].value == "Reason:" + expected
        assert book["Report"]["Q3"].value == capture["qc_header"]["remarks"]
        hosted_export = browser("/api/export", capture)
        assert hosted_export["status"] == 200 and hosted_export["encoding"] == "base64"
        hosted_book = openpyxl.load_workbook(
            io.BytesIO(base64.b64decode(hosted_export["body"]))
        )
        assert hosted_book["Report"]["X2"].value == "Reason:" + expected
        draft_print = client.post("/api/report/print", json=capture)
        assert draft_print.status_code == 200 and expected in draft_print.text
        assert draft_print.text == browser("/api/report/print", capture)["body"]
        confirmed = client.post("/api/finalize", json=payload)
        hosted_confirmed = browser(
            "/api/finalize", payload, "00000000-0000-4000-8000-000000000001"
        )
        assert confirmed.status_code == hosted_confirmed["status"] == 200
        for report in [confirmed.json()["report"], hosted_confirmed["body"]["report"]]:
            assert report["qc_header"]["reason"] == report["generated_reason"] == expected
            assert report["reason_source"] == "defect_summary"
            assert report["qc_header"]["Level_Flag"] == 1
            assert report["samples"][0]["inspector_final_decision"] == "STANDARD"
            assert report["samples"][0]["final_recommendation"] == "EXPAND"
        downloads = confirmed.json()["downloads"]
        saved = client.get(downloads["json"]).json()
        assert saved["qc_header"]["reason"] == expected
        assert client.get(downloads["print"]).status_code == 200
    assert capture["qc_header"]["reason"] == "Stale reason from an earlier capture"
