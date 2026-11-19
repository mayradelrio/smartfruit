"""QC overrides survive confirmation and retain their original photographs."""

import json
import time
from copy import deepcopy
from io import BytesIO

import openpyxl
from fastapi.testclient import TestClient
from PIL import Image

from smartfruit.app import create_app
from smartfruit.inspection import MANUAL_DEFECTS
from smartfruit.vision_capture import VisionCapture


def test_reviewed_counts_and_raw_predictions_survive_all_report_formats(tmp_path):
    images = tmp_path / "input/images"
    images.mkdir(parents=True)
    Image.new("RGB", (40, 20), "green").save(images / "group.jpg")

    def runner(request):
        image = request["images"][0]
        return {"records": [{
            "image_id": image["image_id"], "partition": "capture", "total_fruits": 2,
            "oleocellosis_count": 2, "oleocellosis_pct": 100, "mean_confidence": 0.95,
            "fruit_predictions": [
                {"crop_id": crop, "predicted_class": "con_oleocelosis",
                 "oleocellosis_probability": 0.95, "confidence": 0.95}
                for crop in ("FRUIT_1", "FRUIT_2")
            ],
            "inference": {"input_kind": "scene", "image_size": [40, 20],
                          "fruit_boxes_xyxy": [[0, 0, 20, 20], [20, 0, 40, 20]]},
        }]}

    manager = VisionCapture(tmp_path / "input", tmp_path / "output", runner=runner)
    reports = tmp_path / "reports"
    with TestClient(create_app(reports, False, manager)) as client:
        catalog = client.get("/api/vision/photos").json()
        started = client.post("/api/vision/jobs", json={
            "lot_id": "LOT", "pallet_id": "PALLET", "sample_id": "SAMPLE",
            "photo_ids": [catalog["photos"][0]["photo_id"]],
        }).json()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = client.get(f"/api/vision/jobs/{started['job_id']}").json()
            if job["status"] == "ready":
                break
            time.sleep(0.01)
        assert job["status"] == "ready"
        payload = {
            "qc_header": {"lot_id": "LOT", "Level_Flag": 3, "inspection_date": "2026-11-18"},
            "samples": [{"sample_id": "SAMPLE", "pallet_id": "PALLET",
                         "vision_records": deepcopy(job["records"]),
                         "vision_covers_sample": True,
                         "qc_fields": {item["key"]: 0 for item in MANUAL_DEFECTS}}],
        }
        assert client.post("/api/evaluate", json=payload).status_code == 422
        predictions = payload["samples"][0]["vision_records"][0]["fruit_predictions"]
        for prediction in predictions:
            prediction.update(review_status="confirmed", reviewed_by="QC",
                              reviewed_at="2026-11-18T14:00:00Z", qc_included=True)
        exclusion_reason = "Excluido por QC mediante el check de oleocelosis."
        predictions[1].update(review_status="rejected", override_label="other",
                              override_reason=exclusion_reason, qc_included=False)
        payload.update(inspector_name="QC", confirmed=True,
                       final_decisions={"SAMPLE": "STANDARD"})
        response = client.post("/api/finalize", json=payload)
        assert response.status_code == 200, response.text
        saved = response.json()
        report = saved["report"]
        sample = report["samples"][0]
        assert sample["inspection_summary"]["oleocellosis_count"] == 1
        assert sample["inspection_summary"]["oleocellosis_pct"] == 50
        assert sample["qc_fields"]["scars"] == 0
        assert report["qc_header"]["Level_Flag"] == 3
        assert len(sample["evidence_photos"]) == 2
        assert any(photo["vision_reviews"][0]["review_status"] == "rejected"
                   for photo in sample["evidence_photos"])
        source = json.loads((reports / saved["report_id"] / "source.json").read_text("utf-8"))
        assert source == payload
        audit = sample["inspection_summary"]["vision_review"][1]
        assert audit["predicted_class"] == "con_oleocelosis"
        assert audit["override_label"] == "other"
        assert audit["override_reason"] == exclusion_reason
        assert audit["qc_included"] is False
        workbook = openpyxl.load_workbook(BytesIO(client.get(saved["downloads"]["xlsx"]).content))
        assert workbook["Report"]["R16"].value == 1
        assert workbook["Vision QC"].max_row == 3
        text = client.get(saved["downloads"]["print"]).text
        assert "rejected" in text and exclusion_reason in text
        assert "Level Flag: 3" in text
        assert sample["predictive"]["enabled"] is False
        validation = client.post("/api/vision/validation", json={
            "vision_records": payload["samples"][0]["vision_records"],
        }).json()
        assert validation["metrics"]["false_positives"] == 1
        assert validation["metrics"]["precision"] == 0.5
    manager._executor.shutdown(wait=True)
