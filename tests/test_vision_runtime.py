"""Persistent local worker lifecycle, protocol isolation and cancellation."""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from smartfruit.vision_capture import VisionCapture
from smartfruit.vision_runtime import VisionRuntime

ROOT = Path(__file__).resolve().parents[1]
STUB = r'''
import json, os, sys, time
from pathlib import Path
calls = 0
model_loads = 0
for line in sys.stdin:
    message = json.loads(line)
    action = message.get("action")
    if message.get("entered"):
        Path(message["entered"]).write_text("entered")
    if action == "hang":
        time.sleep(30)
    if action == "crash":
        os._exit(7)
    if action == "malformed":
        print("not-json", flush=True)
        continue
    if action == "wrong_id":
        print(json.dumps({"id":"foreign", "ok":True, "result":{}}), flush=True)
        continue
    if action == "not_object":
        print("[]", flush=True)
        continue
    if action == "missing_ok":
        print(json.dumps({"id":message["id"], "result":{}}), flush=True)
        continue
    if action == "bad_result":
        print(json.dumps({"id":message["id"], "ok":True, "result":[]}), flush=True)
        continue
    if action == "error":
        print(json.dumps({"id":message["id"], "ok":False, "error":"expected failure"}), flush=True)
        continue
    if action == "noisy":
        for _ in range(3000):
            print("library diagnostic " * 20, file=sys.stderr)
        sys.stderr.flush()
    calls += 1
    if message["op"] == "infer":
        request = json.loads(Path(message["request_path"]).read_text())
        model_loads = 1
        records = [{
            "image_id": image["image_id"], "partition":"capture", "total_fruits":1,
            "oleocellosis_count":1, "oleocellosis_pct":100, "mean_confidence":0.9,
            "fruit_predictions":[{"crop_id":image["image_id"]+"_L01",
                "predicted_class":"con_oleocelosis", "confidence":0.9,
                "oleocellosis_probability":0.9}]
        } for image in request["images"]]
        Path(message["output_path"]).write_text(json.dumps({
            "records":records,"pipeline":"stub", "worker_pid":os.getpid(),
            "calls":calls,"model_loads":model_loads}))
    result = {"pid":os.getpid(), "calls":calls, "ready":True,
              "capabilities":{"fruit_crop":True,"scene":True},
              "missing_dependencies":[], "missing_models":[]}
    print(json.dumps({"id":message["id"], "ok":True, "result":result}), flush=True)
'''


@pytest.fixture
def runtime(tmp_path):
    script = tmp_path / "stub_worker.py"
    script.write_text(STUB, "utf-8")
    worker = VisionRuntime(sys.executable, command=[sys.executable, "-u", str(script)])
    try:
        yield worker
    finally:
        worker.close()


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def test_worker_is_lazy_and_reuses_process_for_status_and_two_inferences(runtime, tmp_path):
    assert runtime.pid is None
    initial = runtime.status(tmp_path)
    pid = initial["pid"]
    launched_pid = runtime.pid
    results = []
    for index in range(2):
        request = tmp_path / f"request-{index}.json"
        output = tmp_path / f"output-{index}.json"
        request.write_text(json.dumps({"images": [{"image_id": f"PHOTO_{index}"}]}), "utf-8")
        results.append(runtime.infer(request, output))
    assert {item["worker_pid"] for item in results} == {pid}
    assert [item["calls"] for item in results] == [2, 3]
    assert [item["model_loads"] for item in results] == [1, 1]
    assert [item["records"][0]["image_id"] for item in results] == ["PHOTO_0", "PHOTO_1"]
    # Windows venv launchers may supervise a child with a different os.getpid().
    assert runtime.pid == launched_pid


@pytest.mark.parametrize("action", [
    "crash", "malformed", "wrong_id", "not_object", "missing_ok", "bad_result", "error",
])
def test_failed_worker_is_discarded_and_next_request_starts_cleanly(runtime, action):
    initial = runtime.request("status")
    with pytest.raises((RuntimeError, OSError)):
        runtime.request("status", action=action, timeout=3)
    assert runtime.pid is None
    recovered = runtime.request("status", timeout=3)
    assert recovered["pid"] != initial["pid"]
    assert recovered["calls"] == 1


def test_timeout_terminates_worker_without_automatically_retrying_the_job(runtime):
    original = runtime.request("status")
    with pytest.raises(TimeoutError, match="tiempo de procesamiento"):
        runtime.request("infer", action="hang", timeout=0.2)
    assert runtime.pid is None
    assert runtime.request("status")["pid"] != original["pid"]


def test_close_interrupts_running_request_without_waiting_on_its_lock(runtime, tmp_path):
    entered = tmp_path / "entered"
    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(runtime.request, "infer", action="hang", entered=str(entered))
        wait_until(entered.exists)
        assert runtime.busy
        runtime.close()
        with pytest.raises(RuntimeError, match="cerr"):
            running.result(timeout=3)
    assert runtime.pid is None
    runtime.close()
    with pytest.raises(RuntimeError, match="cerrado"):
        runtime.request("status")


@pytest.mark.skipif(os.name != "nt", reason="Windows venv launcher process-tree cleanup")
def test_windows_close_terminates_the_real_worker_child_as_well_as_its_launcher(runtime):
    import ctypes

    actual_pid = runtime.request("status")["pid"]
    # Hold a handle before termination so a later recycled PID cannot affect
    # this assertion. SYNCHRONIZE is sufficient to wait on our own child.
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, actual_pid)
    assert handle
    try:
        runtime.close()
        assert kernel.WaitForSingleObject(handle, 3000) == 0
    finally:
        kernel.CloseHandle(handle)


def test_status_wait_timeout_never_kills_another_threads_busy_inference(runtime, tmp_path):
    entered = tmp_path / "entered"
    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(runtime.request, "infer", action="hang", entered=str(entered))
        wait_until(entered.exists)
        pid = runtime.pid
        with pytest.raises(TimeoutError, match="ocupado"):
            runtime.request("status", timeout=0.1)
        assert runtime.pid == pid
        runtime.close()
        with pytest.raises(RuntimeError):
            running.result(timeout=3)


def test_library_stderr_is_drained_without_blocking_protocol(runtime):
    result = runtime.request("status", action="noisy", timeout=3)
    assert result["ready"] is True
    assert len(runtime._stderr) <= 20


def test_real_worker_redirects_python_and_native_stdout_and_keeps_imports_light(tmp_path):
    script = tmp_path / "instrumented_worker.py"
    script.write_text('''
import os, sys
from smartfruit import vision_worker
def dispatch(message):
    print("Python library stdout")
    os.write(1, b"Native library stdout\\n")
    return {"torch_imported": "torch" in sys.modules, "pid":os.getpid()}
vision_worker._dispatch = dispatch
vision_worker.main()
''', "utf-8")
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    worker = VisionRuntime(
        sys.executable, environment, command=[sys.executable, "-u", str(script)]
    )
    try:
        first = worker.request("status", timeout=3)
        second = worker.request("status", timeout=3)
        assert first == second
        assert first["torch_imported"] is False
    finally:
        worker.close()


def test_real_worker_preserves_file_protocol_and_python_model_cache_between_jobs(tmp_path):
    script = tmp_path / "instrumented_inference_worker.py"
    script.write_text('''
import os
from functools import lru_cache
from smartfruit import vision_worker
loads = 0
@lru_cache(maxsize=1)
def model():
    global loads
    loads += 1
    return object()
def infer(request):
    model()
    print("library diagnostic")
    return {"records":request["images"], "pid":os.getpid(), "model_loads":loads}
vision_worker.run_request = infer
vision_worker.main()
''', "utf-8")
    worker = VisionRuntime(
        sys.executable, {**os.environ, "PYTHONPATH": str(ROOT / "src")},
        command=[sys.executable, "-u", str(script)],
    )
    try:
        request, output = tmp_path / "request.json", tmp_path / "output.json"
        request.write_text(json.dumps({"images": [{"image_id": "SAME_PHOTO"}]}), "utf-8")
        first = worker.infer(request, output)
        second = worker.infer(request, output)
        assert first == second
        assert second["model_loads"] == 1
        assert second["records"] == [{"image_id": "SAME_PHOTO"}]
    finally:
        worker.close()


def test_capture_reuses_worker_but_preserves_distinct_jobs_snapshots_and_context(runtime, tmp_path):
    photos = tmp_path / "input/images"
    photos.mkdir(parents=True)
    (photos / "FIRST_L01.jpg").write_bytes(b"first-fruit")
    (photos / "SECOND_L02.jpg").write_bytes(b"second-fruit")
    manager = VisionCapture(tmp_path / "input", tmp_path / "output")
    manager._runtime = runtime
    try:
        catalog = manager.catalog()["photos"]
        pid = runtime.pid
        completed = []
        for index, photo in enumerate(catalog):
            started = manager.submit({
                "lot_id": "LOT", "pallet_id": "PAL", "sample_id": f"BOX_{index}",
                "photo_ids": [photo["photo_id"]],
            })
            wait_until(lambda: manager.get(started["job_id"])["status"] in ("ready", "failed"))
            completed.append(manager.get(started["job_id"]))
        assert runtime.pid == pid
        assert all(job["status"] == "ready" for job in completed)
        assert completed[0]["job_id"] != completed[1]["job_id"]
        for index, job in enumerate(completed):
            assert job["context"]["sample_id"] == f"BOX_{index}"
            assert job["image_bindings"][0]["sample_id"] == f"BOX_{index}"
            snapshot = manager.job_photo_path(job["job_id"], catalog[index]["photo_id"])
            assert snapshot.read_bytes() == (photos / catalog[index]["name"]).read_bytes()
            assert (manager.output_dir / job["job_id"] / "response.json").is_file()
    finally:
        manager.close()


def test_capture_uses_last_validated_status_during_busy_worker_even_when_cache_expired(runtime, tmp_path):
    manager = VisionCapture(tmp_path / "input", tmp_path / "output")
    manager._runtime = runtime
    assert manager.runtime_status()["available"] is True
    manager._runtime_cache = ("fruit_crop", manager._runtime_cache[1], time.monotonic() - 60)
    entered = tmp_path / "entered"
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            running = executor.submit(runtime.request, "infer", action="hang", entered=str(entered))
            wait_until(entered.exists)
            assert manager.runtime_status()["available"] is True
            assert manager.runtime_status("scene")["available"] is True
            manager.close()
            with pytest.raises(RuntimeError):
                running.result(timeout=3)
    finally:
        manager.close()


def test_real_worker_status_calls_reuse_process_without_model_weights(tmp_path):
    worker = VisionRuntime(sys.executable, {**os.environ, "PYTHONPATH": str(ROOT / "src")})
    try:
        first = worker.status(tmp_path / "missing-models")
        pid = worker.pid
        second = worker.status(tmp_path / "missing-models", "scene")
        assert first["ready"] is False and second["ready"] is False
        assert worker.pid == pid
    finally:
        worker.close()
