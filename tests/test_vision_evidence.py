"""Las miniaturas de resultados muestran la copia exacta que procesó cada trabajo."""

import time

import pytest
from fastapi.testclient import TestClient

from smartfruit.app import create_app
from smartfruit.vision_capture import VisionCapture


def _runner(request):
    return {"records": [
        {"image_id": image["image_id"], "partition": "capture", "total_fruits": 1,
         "oleocellosis_count": 1, "oleocellosis_pct": 100, "mean_confidence": 0.9,
         "fruit_predictions": [{"crop_id": image["image_id"] + "_L01",
                                "predicted_class": "con_oleocelosis",
                                "oleocellosis_probability": 0.9, "confidence": 0.9}]}
        for image in request["images"]
    ]}


@pytest.fixture
def evidence(tmp_path):
    source = tmp_path / "input"
    (source / "images").mkdir(parents=True)
    (source / "images/IMG_1_L01.jpg").write_bytes(b"original-first-fruit")
    (source / "images/IMG_2_L01.jpg").write_bytes(b"original-second-fruit")
    manager = VisionCapture(source, tmp_path / "output", runner=_runner)
    with TestClient(create_app(tmp_path / "reports", False, manager)) as client:
        photos = client.get("/api/vision/photos").json()["photos"]
        yield client, manager, photos
    manager.close()


def _ready(client, photo):
    response = client.post("/api/vision/jobs", json={
        "lot_id": "ANY-LOT", "pallet_id": "ANY-PALLET", "sample_id": "ANY-SAMPLE",
        "review_kind": "initial", "photo_ids": [photo["photo_id"]],
    })
    assert response.status_code == 202
    job = response.json()
    deadline = time.monotonic() + 3
    while job["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.01)
        job = client.get("/api/vision/jobs/" + job["job_id"]).json()
    assert job["status"] == "ready", job
    return job


def _url(job, photo):
    return f"/api/vision/jobs/{job['job_id']}/photos/{photo['photo_id']}/image"


def test_result_image_uses_immutable_input_after_arrival_file_removed(evidence):
    client, manager, photos = evidence
    photo = photos[0]
    job = _ready(client, photo)
    (manager.photos_dir / photo["name"]).unlink()
    response = client.get(_url(job, photo))
    assert response.status_code == 200
    assert response.content == b"original-first-fruit"
    assert response.headers["content-type"] == "image/jpeg"


def test_evidence_is_limited_to_selected_images_of_that_job(evidence):
    client, _, photos = evidence
    first = _ready(client, photos[0])
    second = _ready(client, photos[1])
    assert client.get(_url(first, photos[0])).status_code == 200
    assert client.get(_url(second, photos[1])).status_code == 200
    assert client.get(_url(first, photos[1])).status_code == 404
    assert client.get(_url(second, photos[0])).status_code == 404


@pytest.mark.parametrize("job_id,photo_id", [
    ("not-a-uuid", "PHOTO_nonexistent"),
    ("3211b63b-ef8f-4f85-9f66-ab581ad41be4", "PHOTO_nonexistent"),
    ("..%2Foutside", "PHOTO_nonexistent"),
])
def test_evidence_rejects_unknown_or_malformed_identifiers(evidence, job_id, photo_id):
    client, _, _ = evidence
    response = client.get(f"/api/vision/jobs/{job_id}/photos/{photo_id}/image")
    assert response.status_code == 404


def test_evidence_can_be_loaded_from_persisted_job_after_restart(evidence):
    client, manager, photos = evidence
    photo = photos[0]
    job = _ready(client, photo)
    restored = VisionCapture(manager.input_dir, manager.output_dir.parent, runner=_runner)
    try:
        assert restored.job_photo_path(job["job_id"], photo["photo_id"]).read_bytes() == (
            b"original-first-fruit"
        )
    finally:
        restored.close()


def test_evidence_does_not_follow_snapshot_link_outside_job(evidence, tmp_path):
    client, manager, photos = evidence
    photo = photos[0]
    job = _ready(client, photo)
    snapshot = manager.job_photo_path(job["job_id"], photo["photo_id"])
    outside = tmp_path / "unrelated.jpg"
    outside.write_bytes(b"outside-private-file")
    snapshot.unlink()
    try:
        snapshot.symlink_to(outside)
    except OSError:
        pytest.skip("This Windows account cannot create file symlinks")
    assert client.get(_url(job, photo)).status_code == 404
