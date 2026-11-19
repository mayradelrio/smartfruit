"""Transporte local: fotos, procesamiento asíncrono y contexto comercial conservado."""

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smartfruit.app import create_app
from smartfruit.vision_capture import VisionCapture


def _result(request):
    return {"pipeline": "test-runner", "records": [
        {"image_id": image["image_id"], "partition": "capture", "total_fruits": 1,
         "oleocellosis_count": 1, "oleocellosis_pct": 100, "mean_confidence": 0.8,
         "fruit_predictions": [{"crop_id": image["image_id"] + "_L01",
                                "predicted_class": "con_oleocelosis",
                                "oleocellosis_probability": 0.8, "confidence": 0.8}]}
        for image in request["images"]
    ]}


@pytest.fixture
def setup(tmp_path):
    source = tmp_path / "input"
    (source / "images").mkdir(parents=True)
    (source / "images/IMG_42_L01.jpg").write_bytes(b"fruit-one")
    (source / "images/IMG_42_L02.jpg").write_bytes(b"fruit-two")
    (source / "images/copy.jpg").write_bytes(b"fruit-one")
    manager = VisionCapture(source, tmp_path / "output", runner=_result)
    with TestClient(create_app(tmp_path / "reports", False, manager)) as client:
        yield client, manager
    manager._executor.shutdown(wait=True)


def _payload(client, **values):
    photos = client.get("/api/vision/photos").json()["photos"]
    return {"lot_id": "ANY-LOT", "pallet_id": "ANY-PALLET", "sample_id": "ANY-SAMPLE",
            "review_kind": "initial", "photo_ids": [photo["photo_id"] for photo in photos],
            **values}


def _finish(client, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/api/vision/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in ("ready", "failed"):
            return job
        time.sleep(0.01)
    pytest.fail("Vision job did not finish")


def test_catalog_deduplicates_content_and_groups_crops_without_exposing_paths(setup):
    client, _ = setup
    catalog = client.get("/api/vision/photos").json()
    assert catalog["runtime"]["available"] is True
    assert len(catalog["photos"]) == 2
    assert {photo["source_group"] for photo in catalog["photos"]} == {"IMG_42"}
    assert all(photo["input_kind"] == "fruit_crop" for photo in catalog["photos"])
    photo = catalog["photos"][0]
    assert "_path" not in photo
    assert photo["image_id"] == photo["photo_id"]
    image = client.get(photo["url"])
    assert image.status_code == 200
    assert image.content == b"fruit-one"
    assert client.get("/api/vision/photos/nonexistent/image").status_code == 404


def test_real_transport_persists_generated_json_bound_to_selected_context(setup):
    client, manager = setup
    payload = _payload(client)
    started = client.post("/api/vision/jobs", json=payload)
    assert started.status_code == 202
    job = _finish(client, started.json()["job_id"])
    assert job["status"] == "ready"
    assert job["progress"] == {"completed": 2, "total": 2}
    assert len(job["records"]) == 2
    assert job["context"] == {k: payload[k] for k in
                              ("lot_id", "pallet_id", "sample_id", "review_kind")}
    assert all(binding["pallet_id"] == "ANY-PALLET" for binding in job["image_bindings"])
    folder = manager.output_dir / job["job_id"]
    assert len(list(folder.glob("PHOTO_*.json"))) == 2
    stored = json.loads((folder / "job.json").read_text("utf-8"))
    assert stored["records"] == job["records"]
    replacement = VisionCapture(manager.input_dir, manager.output_dir.parent, runner=_result)
    assert replacement.get(job["job_id"])["context"] == job["context"]
    replacement._executor.shutdown(wait=True)


def test_additional_review_keeps_its_own_target_without_overwriting_initial_job(setup):
    client, _ = setup
    initial = client.post("/api/vision/jobs", json=_payload(client)).json()
    extra = client.post("/api/vision/jobs", json=_payload(
        client, pallet_id="SECOND-PALLET", sample_id="SECOND-SAMPLE", review_kind="additional"
    )).json()
    initial = _finish(client, initial["job_id"])
    extra = _finish(client, extra["job_id"])
    assert initial["context"]["pallet_id"] == "ANY-PALLET"
    assert extra["context"]["pallet_id"] == "SECOND-PALLET"
    assert extra["context"]["review_kind"] == "additional"
    assert initial["records"] == extra["records"]


@pytest.mark.parametrize("values", [
    {"lot_id": ""}, {"pallet_id": 5645}, {"sample_id": None},
    {"review_kind": "made-up"}, {"photo_ids": []}, {"photo_ids": ["C:/private.jpg"]},
    {"photo_ids": "image"},
])
def test_job_requires_identified_context_and_catalog_selection(setup, values):
    client, _ = setup
    response = client.post("/api/vision/jobs", json=_payload(client, **values))
    assert response.status_code == 422


def test_same_photo_cannot_be_submitted_twice(setup):
    client, _ = setup
    payload = _payload(client)
    payload["photo_ids"] *= 2
    assert client.post("/api/vision/jobs", json=payload).status_code == 422


def test_job_uses_copies_even_when_arrival_folder_changes(setup):
    client, manager = setup
    entered, release = threading.Event(), threading.Event()
    observed = []

    def paused(request):
        entered.set()
        assert release.wait(timeout=3)
        observed.extend(Path(image["path"]).read_bytes() for image in request["images"])
        return _result(request)

    manager._runner = paused
    started = client.post("/api/vision/jobs", json=_payload(client)).json()
    try:
        assert entered.wait(timeout=3)
        for photo in manager.photos_dir.iterdir():
            photo.write_bytes(b"different-arrival")
    finally:
        release.set()
    job = _finish(client, started["job_id"])
    assert job["status"] == "ready"
    assert set(observed) == {b"fruit-one", b"fruit-two"}


def test_foreign_result_never_becomes_a_ready_job(setup):
    client, manager = setup

    def wrong(request):
        result = _result(request)
        result["records"][0]["image_id"] = "OTHER-IMAGE"
        return result

    manager._runner = wrong
    job = client.post("/api/vision/jobs", json=_payload(client)).json()
    failed = _finish(client, job["job_id"])
    assert failed["status"] == "failed"
    assert failed["records"] == []
    assert not list((manager.output_dir / job["job_id"]).glob("PHOTO_*.json"))


def test_restart_interrupts_unfinished_job_without_returning_partial_results(setup):
    _, manager = setup
    job_id = "3211b63b-ef8f-4f85-9f66-ab581ad41be4"
    folder = manager.output_dir / job_id
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps({"status": "running", "records": []}), "utf-8")
    restored = manager.get(job_id)
    assert restored["status"] == "failed"
    assert "reinici" in restored["error"]
    assert restored["records"] == []
    with pytest.raises(KeyError):
        manager.get("../private")


def test_catalog_does_not_follow_links_outside_input_folder(setup, tmp_path):
    _, manager = setup
    private = tmp_path / "private.jpg"
    private.write_bytes(b"private")
    try:
        (manager.photos_dir / "outside.jpg").symlink_to(private)
    except OSError:
        pytest.skip("This Windows account cannot create file symlinks")
    assert len(manager.catalog()["photos"]) == 2
