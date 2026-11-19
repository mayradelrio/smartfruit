"""Observable Vision processing, duplicate requests and safe retries."""

import json
import threading
import time

import pytest

from smartfruit.vision_capture import VisionCapture


def result(request):
    return {"records": [
        {"image_id": image["image_id"], "partition": "capture", "total_fruits": 0,
         "oleocellosis_count": 0, "oleocellosis_pct": 0, "mean_confidence": None,
         "fruit_predictions": []}
        for image in request["images"]
    ]}


@pytest.fixture
def manager(tmp_path):
    images = tmp_path / "input/images"
    images.mkdir(parents=True)
    (images / "group.jpg").write_bytes(b"group photograph")
    capture = VisionCapture(tmp_path / "input", tmp_path / "output", runner=result)
    yield capture
    capture.close()
    capture._executor.shutdown(wait=True)


def payload(manager):
    return {"lot_id": "LOT", "pallet_id": "PALLET", "sample_id": "SAMPLE",
            "photo_ids": [photo["photo_id"] for photo in manager.catalog()["photos"]]}


def finished(manager, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job["status"] in ("ready", "failed"):
            return job
        time.sleep(0.01)
    pytest.fail("job did not finish")


def test_duplicate_active_submit_returns_same_job_and_reports_real_progress(manager):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def paused(request):
        calls.append(request)
        entered.set()
        assert release.wait(3)
        return result(request)

    manager._runner = paused
    request = payload(manager)
    initial = manager.submit(request)
    try:
        assert initial["phase"] == "QUEUED"
        assert entered.wait(3)
        repeated = manager.submit(request)
        assert repeated["job_id"] == initial["job_id"]
        progress_path = manager.output_dir / initial["job_id"] / "progress.json"
        progress_path.write_text(json.dumps({"completed": 0, "total": 1,
                                             "phase": "CLASSIFYING", "detected_fruits": 74}))
        observed = manager.get(initial["job_id"])
        assert observed["phase"] == "CLASSIFYING"
        assert observed["progress"]["detected_fruits"] == 74
    finally:
        release.set()
    assert finished(manager, initial["job_id"])["phase"] == "REVIEW_READY"
    assert len(calls) == 1


@pytest.mark.parametrize("exception, phase, kind", [
    (TimeoutError("El worker no responde"), "TIMEOUT", "timeout"),
    (RuntimeError("No se pudo procesar la foto"), "ERROR", "error"),
])
def test_failed_jobs_identify_timeout_and_allow_explicit_retry(manager, exception, phase, kind):
    def fail(request):
        raise exception

    manager._runner = fail
    request = payload(manager)
    failed = finished(manager, manager.submit(request)["job_id"])
    assert failed["status"] == "failed"
    assert failed["phase"] == phase
    assert failed["error_type"] == kind
    assert failed["error"] == str(exception)
    manager._runner = result
    retry = finished(manager, manager.submit(request)["job_id"])
    assert retry["job_id"] != failed["job_id"]
    assert retry["phase"] == "REVIEW_READY"
