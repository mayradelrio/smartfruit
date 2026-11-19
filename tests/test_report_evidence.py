"""Only positive Vision predictions acquire self-contained local photographic proof."""

import base64
import json
import runpy
import time
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from review_helpers import confirm_vision_records

from smartfruit.app import create_app
from smartfruit.inspection import MANUAL_DEFECTS
from smartfruit.report_evidence import attach_report_evidence
from smartfruit.vision_capture import VisionCapture
from smartfruit.workflow import evaluate_inspection


def record(image_id, positive=(0,), total=1, inference=None, crop_ids=None):
    result = {
        "image_id": image_id, "partition": "test", "total_fruits": total,
        "oleocellosis_count": len(positive), "oleocellosis_pct": 100 * len(positive) / total,
        "mean_confidence": 0.9,
        "fruit_predictions": [{
            "crop_id": crop_ids[index] if crop_ids else f"{image_id}_L{index + 1:02}.jpg",
            "predicted_class": "con_oleocelosis" if index in positive else "sin_oleocelosis",
            "confidence": 0.9, "oleocellosis_probability": 0.9 if index in positive else 0.1,
        } for index in range(total)],
    }
    if inference is not None:
        result["inference"] = inference
    return result


def capture(records):
    return {
        "qc_header": {"lot_id": "LOT", "inspection_date": "2026-11-16"},
        "samples": [{
            "sample_id": "S1", "pallet_id": "PAL", "vision_records": confirm_vision_records(records),
            "vision_covers_sample": True,
            "qc_fields": {column["key"]: 0 for column in MANUAL_DEFECTS},
            "box_inspection": {
                "sample_box_id": "BOX_001", "status": "completed", "coverage_confirmed": True,
            },
        }],
    }


def runner(request):
    records = []
    for photo in request["images"]:
        name = Path(photo["path"]).name
        with Image.open(photo["path"]) as image:
            size = list(image.size)
        metadata = {
            "input_kind": photo["input_kind"], "source_filename": name, "image_size": size,
        }
        if photo["input_kind"] == "scene":
            metadata["fruit_boxes_xyxy"] = [[0, 0, 30, 30], [30, 0, 60, 30], [60, 0, 90, 30]]
            records.append(record(photo["image_id"], (0, 2), 3, metadata))
        else:
            records.append(record(photo["image_id"], (0,) if name.startswith("BAD") else (), 1, metadata))
    return {"records": records}


@pytest.fixture
def local(tmp_path):
    photos = tmp_path / "input/images"
    photos.mkdir(parents=True)
    Image.new("RGB", (60, 40), "red").save(photos / "BAD_L01.jpg")
    Image.new("RGB", (60, 40), "green").save(photos / "GOOD_L02.jpg")
    scene = Image.new("RGB", (90, 30), "red")
    scene.paste("green", (30, 0, 60, 30))
    scene.paste("blue", (60, 0, 90, 30))
    scene.save(photos / "GROUP.jpg")
    manager = VisionCapture(tmp_path / "input", tmp_path / "output", runner=runner)
    with TestClient(create_app(tmp_path / "reports", False, manager)) as client:
        yield client, manager


def ready(manager, name):
    photo = next(item for item in manager.catalog()["photos"] if item["name"] == name)
    job = manager.submit({
        "lot_id": "LOT", "pallet_id": "PAL", "sample_id": "S1", "photo_ids": [photo["photo_id"]],
    })
    deadline = time.monotonic() + 3
    while job["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.01)
        job = manager.get(job["job_id"])
    assert job["status"] == "ready", job
    return job


def decoded(photo):
    return Image.open(BytesIO(base64.b64decode(photo["image_data_url"].split(",", 1)[1])))


def test_ready_scene_attaches_only_positive_aligned_crops_without_source_names(local):
    client, manager = local
    job = ready(manager, "GROUP.jpg")
    payload = capture(job["records"])
    payload["samples"][0]["evidence_photos"] = [{
        "image_data_url": "https://attacker.invalid/private.jpg", "defect": "oleocellosis",
    }]
    expected = evaluate_inspection(payload)["samples"][0]
    response = client.post("/api/evaluate", json=payload)
    assert response.status_code == 200, response.text
    sample = response.json()["samples"][0]
    assert sample["final_recommendation"] == expected["final_recommendation"]
    assert sample["inspection_summary"] == expected["inspection_summary"]
    assert sample["defects"] == expected["defects"]
    assert len(sample["evidence_photos"]) == 2
    assert sample["evidence_summary"] == {
        "status": "available", "positive_fruits": 2, "attached_fruits": 2,
        "attached_photos": 2, "unavailable_fruits": 0,
        "message": "Evidencia de Vision adjunta con revisión QC.",
    }
    first, second = sample["evidence_photos"]
    for photo in (first, second):
        assert photo["sample_box_id"] == "BOX_001"
        assert photo["view"] == "fruit_crop" and photo["defect"] == "oleocellosis"
        assert photo["width"] == photo["height"] == 30
        assert "GROUP" not in json.dumps(photo) and "PHOTO_" not in json.dumps(photo)
        assert not decoded(photo).getexif()
    red, blue = decoded(first).getpixel((15, 15)), decoded(second).getpixel((15, 15))
    assert red[0] > 180 and red[1] < 80 and red[2] < 80
    assert blue[2] > 180 and blue[0] < 80 and blue[1] < 80


def test_scene_without_aligned_boxes_is_honestly_labeled_and_attached_once(local):
    client, manager = local
    photo = next(p for p in manager.catalog()["photos"] if p["name"] == "GROUP.jpg")
    source = record(photo["image_id"], (0, 2), 3, {
        "input_kind": "scene", "source_filename": "GROUP.jpg", "image_size": [90, 30],
        "fruit_boxes_xyxy": [[0, 0, 30, 30]],
    })
    sample = client.post("/api/evaluate", json=capture([source])).json()["samples"][0]
    assert len(sample["evidence_photos"]) == 1
    evidence = sample["evidence_photos"][0]
    assert evidence["view"] == "scene" and evidence["affected_fruits"] == 2
    assert evidence["width"] == 90 and evidence["height"] == 30
    assert "grupal" in evidence["caption"] and "revisión QC" in evidence["caption"]
    assert sample["evidence_summary"]["attached_fruits"] == 2


def test_historical_crop_names_resolve_only_positive_fruits(local):
    client, _ = local
    source = record("OLD_GROUP", (0,), 2, crop_ids=["BAD_L01.jpg", "GOOD_L02.jpg"])
    sample = client.post("/api/evaluate", json=capture([source])).json()["samples"][0]
    assert len(sample["evidence_photos"]) == 1
    assert sample["evidence_summary"]["positive_fruits"] == 1
    assert decoded(sample["evidence_photos"][0]).getpixel((20, 20))[0] > 180


@pytest.mark.parametrize("filename", ["../outside.jpg", "https://example.invalid/outside.jpg", "C:\\outside.jpg"])
def test_client_paths_and_urls_never_supply_report_images(local, tmp_path, filename):
    client, _ = local
    Image.new("RGB", (30, 30), "red").save(tmp_path / "outside.jpg")
    source = record("UNKNOWN", inference={"source_filename": filename}, crop_ids=[filename])
    payload = capture([source])
    payload["evidence_photos"] = [{"image_data_url": "data:image/jpeg;base64,INJECTED"}]
    response = client.post("/api/evaluate", json=payload)
    assert response.status_code == 200, response.text
    sample = response.json()["samples"][0]
    assert sample["evidence_photos"] == []
    assert sample["evidence_summary"]["status"] == "unavailable"


def test_modified_local_predictions_cannot_borrow_a_known_jobs_photographic_proof(local):
    client, manager = local
    job = ready(manager, "GOOD_L02.jpg")
    changed = deepcopy(job["records"][0])
    changed["fruit_predictions"][0].update(
        predicted_class="con_oleocelosis", oleocellosis_probability=0.9
    )
    changed.update(oleocellosis_count=1, oleocellosis_pct=100)
    response = client.post("/api/evaluate", json=capture([changed]))
    assert response.status_code == 200, response.text
    sample = response.json()["samples"][0]
    assert sample["evidence_photos"] == []
    assert sample["evidence_summary"]["unavailable_fruits"] == 1


def test_immutable_job_photo_and_persisted_report_survive_source_removal_and_restart(local, tmp_path):
    client, manager = local
    job = ready(manager, "BAD_L01.jpg")
    (manager.photos_dir / "BAD_L01.jpg").unlink()
    payload = capture(job["records"])
    payload.update(
        inspector_name="Inspector TEST", confirmed=True, final_decisions={"S1": "STANDARD"}
    )
    saved = client.post("/api/finalize", json=payload)
    assert saved.status_code == 200, saved.text
    result = saved.json()
    evidence = result["report"]["samples"][0]["evidence_photos"]
    assert len(evidence) == 1
    assert decoded(evidence[0]).getpixel((20, 20))[0] > 180
    stored = json.loads((tmp_path / "reports" / result["report_id"] / "report.json").read_text("utf-8"))
    assert stored["samples"][0]["evidence_photos"] == evidence
    restored = VisionCapture(tmp_path / "empty-input", tmp_path / "empty-output", runner=runner)
    with TestClient(create_app(tmp_path / "reports", False, restored)) as restart:
        report = restart.get(result["downloads"]["json"]).json()
        assert report["samples"][0]["evidence_photos"] == evidence
        printed = restart.get(result["downloads"]["print"])
        assert printed.status_code == 200
        assert evidence[0]["image_data_url"] in printed.text


def test_missing_and_invalid_photos_do_not_change_rules_or_claim_healthy_images(local):
    client, manager = local
    job = ready(manager, "GOOD_L02.jpg")
    healthy = client.post("/api/evaluate", json=capture(job["records"])).json()["samples"][0]
    assert healthy["evidence_photos"] == []
    assert healthy["evidence_summary"]["status"] == "no_defects"
    (manager.photos_dir / "INVALID_L01.jpg").write_bytes(b"not an image")
    invalid = capture([record("OLD", crop_ids=["INVALID_L01.jpg"])])
    sample = client.post("/api/evaluate", json=invalid).json()["samples"][0]
    assert sample["evidence_photos"] == []
    assert sample["evidence_summary"]["status"] == "unavailable"
    assert sample["final_recommendation"] == evaluate_inspection(invalid)["samples"][0]["final_recommendation"]


def test_browser_only_reports_do_not_fabricate_or_accept_injected_images():
    root = Path(__file__).resolve().parents[1]
    dispatch = runpy.run_path(str(root / "hosting/browser/browser_api.py"))["smartfruit_browser_api"]
    payload = capture([record("MISSING")])
    payload["samples"][0]["evidence_photos"] = [{
        "image_data_url": "data:image/jpeg;base64,INJECTED", "defect": "oleocellosis",
    }]
    response = json.loads(dispatch("POST", "/api/evaluate", json.dumps(payload)))
    assert response["status"] == 200
    sample = response["body"]["samples"][0]
    assert sample["evidence_photos"] == []
    assert sample["evidence_summary"]["status"] == "unavailable"


def test_normalization_bounds_image_size_and_removes_source_metadata():
    image = Image.new("RGB", (2000, 1500), "red")
    exif = Image.Exif()
    exif[270] = "private-source-filename.jpg"
    data = BytesIO()
    image.save(data, format="JPEG", exif=exif)
    payload = capture([record("SOURCE")])
    report = attach_report_evidence(
        evaluate_inspection(payload), payload,
        lambda *_: {"image_bytes": data.getvalue(), "input_kind": "fruit_crop"},
    )
    photo = report["samples"][0]["evidence_photos"][0]
    assert photo["width"] == 1024 and photo["height"] == 768
    assert not decoded(photo).getexif()
    assert b"private-source" not in base64.b64decode(photo["image_data_url"].split(",", 1)[1])
