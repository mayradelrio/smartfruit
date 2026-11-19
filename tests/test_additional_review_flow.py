"""The additional-box action is atomic across API, browser transport and saved reports."""

import json
import runpy
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smartfruit.app import create_app
from smartfruit.inspection import MANUAL_DEFECTS
from smartfruit.vision_capture import VisionCapture

ROOT = Path(__file__).resolve().parents[1]


def manual(**changes):
    return {**{column["key"]: 0 for column in MANUAL_DEFECTS}, **changes}


def browser(path, payload):
    dispatch = runpy.run_path(str(ROOT / "hosting/browser/browser_api.py"))[
        "smartfruit_browser_api"
    ]
    return json.loads(dispatch("POST", path, json.dumps(payload)))


@pytest.fixture
def capture():
    records = [json.loads((ROOT / f"examples/vision/IMG_{number}.json").read_text())
               for number in (6426, 6427, 6428)]
    return {
        "qc_header": {"lot_id": "TEST-LOT", "inspection_date": "2026-11-15", "Level_Flag": 2},
        "reason_source": "defect_summary",
        "samples": [{
            "sample_id": f"S{index + 1}", "pallet_id": f"P{index + 1}",
            "vision_records": [record], "vision_covers_sample": True,
            "qc_fields": {"pallet_id": f"P{index + 1}", **manual(scars=index + 1)},
            "review_choice": "EXPAND" if index == 0 else "ESCALATE",
        } for index, record in enumerate(records[:2])],
    }, records[2]


def test_preview_apply_repeat_and_confirm_keep_one_pallet_with_review_history(capture, tmp_path):
    current, extra = capture
    original = deepcopy(current)
    manager = VisionCapture(tmp_path / "vision-input", tmp_path / "vision-output")
    with TestClient(create_app(tmp_path, False, manager)) as client:
        preview_body = {**current, "sample_id": "S1", "vision_records": [extra]}
        preview = client.post("/api/inspection/additional-review/preview", json=preview_body)
        assert preview.status_code == 200, preview.text
        assert preview.json() == browser("/api/inspection/additional-review/preview", preview_body)["body"]
        assert current == original
        request = {
            **current, "sample_id": "S1", "inspector_decision": "EXTEND",
            "additional_review": {
                "vision_records": [extra], "manual_defects": manual(scars=3),
                "observations": "Second box",
            },
        }
        applied = client.post("/api/inspection/additional-review", json=request)
        assert applied.status_code == 200, applied.text
        assert applied.json() == browser("/api/inspection/additional-review", request)["body"]
        current = applied.json()["capture"]
        target = current["samples"][0]
        total = original["samples"][0]["vision_records"][0]["total_fruits"] + extra["total_fruits"]
        assert target["qc_fields"]["sample_count"] == total
        assert target["qc_fields"]["scars"] == 4
        assert target["review_choice"] == ""
        assert current["samples"][1] == original["samples"][1]
        assert len(target["review_history"]["additional"]) == 1

        # The preview accepts another box through the dedicated route after history exists.
        third = deepcopy(extra)
        third["image_id"] = "TEST-THIRD-BOX"
        again = {**current, "sample_id": "S1", "vision_records": [third]}
        assert client.post("/api/vision/import", json=again).status_code == 422
        assert client.post("/api/inspection/additional-review/preview", json=again).status_code == 200
        current["samples"][0]["review_choice"] = "EXPAND"
        request = {
            **current, "sample_id": "S1", "inspector_decision": "EXPAND",
            "additional_review": {"vision_records": [third], "manual_defects": manual()},
        }
        applied = client.post("/api/inspection/additional-review", json=request)
        assert applied.status_code == 200, applied.text
        current = applied.json()["capture"]
        assert len(current["samples"][0]["review_history"]["additional"]) == 2
        assert current["samples"][0]["qc_fields"]["sample_count"] == total + third["total_fruits"]
        report = applied.json()["report"]
        assert report["qc_header"]["reason"] == report["generated_reason"]

        saved = client.post("/api/finalize", json={
            **current, "confirmed": True, "inspector_name": "Inspector TEST",
            "final_decisions": {"S1": "STANDARD", "S2": "ESCALATE"},
        })
        assert saved.status_code == 200, saved.text
        downloads = saved.json()["downloads"]
        record = client.get(downloads["json"]).json()
        assert record["samples"][0]["review_history"] == current["samples"][0]["review_history"]
        assert record["samples"][0]["inspector_final_decision"] == "STANDARD"
        assert record["samples"][1]["inspector_final_decision"] == "ESCALATE"
        assert client.get(downloads["print"]).status_code == 200
        assert client.get(downloads["xlsx"]).status_code == 200


def test_failed_additional_request_does_not_change_capture_or_create_a_report(capture, tmp_path):
    current, _ = capture
    before = deepcopy(current)
    bad = {
        **current, "sample_id": "S1", "inspector_decision": "EXTEND",
        "additional_review": {
            "vision_records": current["samples"][0]["vision_records"], "manual_defects": manual(),
        },
    }
    with TestClient(create_app(tmp_path, False)) as client:
        response = client.post("/api/inspection/additional-review", json=bad)
    assert response.status_code == 422 and "ya se utilizaron" in response.json()["detail"]
    assert browser("/api/inspection/additional-review", bad)["status"] == 422
    assert current == before
    assert list(tmp_path.iterdir()) == []
