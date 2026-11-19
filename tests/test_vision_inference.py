"""Contrato de inferencia y separación del runtime opcional de Vision."""

import json

import pytest

from smartfruit import vision_inference as inference
from smartfruit.vision import aggregate_vision_sample, validate_vision_record


def test_probability_mapping_uses_checkpoint_order_and_preserves_precision():
    classes = {"sin_oleocelosis": 0, "con_oleocelosis": 1}
    predictions = inference._predictions_from_probabilities(
        [[0.8, 0.2], [0.123456789, 0.876543211]], classes, "PHOTO"
    )
    result = inference._record("PHOTO", "capture", predictions, {})
    validate_vision_record(result)
    assert result["total_fruits"] == 2
    assert result["oleocellosis_count"] == 1
    assert result["oleocellosis_pct"] == 50
    assert predictions[0]["predicted_class"] == "sin_oleocelosis"
    assert predictions[0]["oleocellosis_probability"] == 0.2
    assert predictions[1]["oleocellosis_probability"] == 0.876543211
    assert predictions[1]["confidence"] == 0.876543211
    assert predictions[0]["crop_id"] != predictions[1]["crop_id"]


@pytest.mark.parametrize("mapping", [
    {"con_oleocelosis": 0, "sin_oleocelosis": 0},
    {"con_oleocelosis": False, "sin_oleocelosis": True},
    {"healthy": 0, "affected": 1},
])
def test_unknown_or_ambiguous_checkpoint_classes_are_rejected(mapping):
    with pytest.raises(ValueError):
        inference._predictions_from_probabilities([[0.1, 0.9]], mapping, "PHOTO")


def test_empty_scene_is_a_valid_zero_count_without_fabricating_fruit():
    result = inference._record("EMPTY", "capture", [], {"input_kind": "scene"})
    validate_vision_record(result)
    assert result["total_fruits"] == result["oleocellosis_count"] == 0
    assert result["mean_confidence"] is None


def test_crop_runtime_does_not_require_yolo_or_detector_weights(tmp_path, monkeypatch):
    (tmp_path / inference.CLASSIFIER_FILENAME).write_bytes(b"checkpoint")
    monkeypatch.setattr(
        inference.importlib.util, "find_spec",
        lambda name: None if name == "ultralytics" else object(),
    )
    status = inference.get_runtime_status(tmp_path, "fruit_crop")
    assert status["ready"] is True
    assert status["capabilities"] == {"fruit_crop": True, "scene": False}
    assert status["missing_dependencies"] == status["missing_models"] == []
    scene_status = inference.get_runtime_status(tmp_path, "scene")
    assert scene_status["ready"] is False
    assert scene_status["missing_models"] == [inference.DETECTOR_FILENAME]
    assert scene_status["missing_dependencies"] == ["ultralytics"]


def test_missing_file_is_rejected_without_loading_models(tmp_path):
    with pytest.raises(ValueError, match="imagen"):
        inference.infer_image(tmp_path / "missing.jpg", input_kind="fruit_crop")


def test_cli_preserves_bound_image_ids_and_updates_progress(tmp_path, monkeypatch):
    calls = []

    def fake_infer(path, **kwargs):
        calls.append((path, kwargs))
        probabilities = [[0.9, 0.1]] if len(calls) == 1 else [[0.1, 0.9]]
        predictions = inference._predictions_from_probabilities(
            probabilities, {"con_oleocelosis": 0, "sin_oleocelosis": 1},
            kwargs["image_id"],
        )
        return inference._record(kwargs["image_id"], kwargs["partition"], predictions, {})

    def fake_crop_batch(images, *, models_dir=None):
        return [fake_infer(item["path"], models_dir=models_dir, **{
            key: item[key] for key in ("image_id", "partition", "input_kind")
        }) for item in images]

    monkeypatch.setattr(inference, "_infer_crop_batch", fake_crop_batch)
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "output.json"
    progress_path = tmp_path / "progress.json"
    request_path.write_text(json.dumps({
        "models_dir": str(tmp_path), "partition": "capture", "input_kind": "fruit_crop",
        "images": [
            {"path": "a.jpg", "image_id": "INSPECTION-A"},
            {"path": "b.jpg", "image_id": "INSPECTION-B"},
        ],
        "progress_path": str(progress_path),
    }), encoding="utf-8")
    assert inference.main(["--request", str(request_path), "--output", str(output_path)]) == 0
    records = json.loads(output_path.read_text(encoding="utf-8"))["records"]
    summary = aggregate_vision_sample(records, "SAMPLE")["vision_summary"]
    assert summary["image_ids"] == ["INSPECTION-A", "INSPECTION-B"]
    assert summary["total_fruits"] == 2
    assert summary["oleocellosis_count"] == 0
    assert summary["suspected_oleocellosis_count"] == 1
    assert summary["pending_review_count"] == 1
    assert all(kwargs["input_kind"] == "fruit_crop" for _, kwargs in calls)
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["completed"] == 2 and progress["total"] == 2
    assert progress["detected_fruits"] == 2


def test_cli_failure_leaves_explicit_error_and_partial_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(
        inference, "infer_image", lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("Modelo incompatible")
        ),
    )
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "output.json"
    progress_path = tmp_path / "progress.json"
    request_path.write_text(json.dumps({
        "images": [{"path": "bad.jpg"}], "progress_path": str(progress_path),
    }), encoding="utf-8")
    assert inference.main(["--request", str(request_path), "--output", str(output_path)]) == 1
    assert json.loads(output_path.read_text(encoding="utf-8")) == {"error": "Modelo incompatible"}
    assert json.loads(progress_path.read_text(encoding="utf-8")) == {
        "completed": 0, "total": 1, "phase": "LOADING_MODEL",
    }


def test_locked_progress_never_discards_successful_predictions(tmp_path, monkeypatch):
    progress_path = tmp_path / "progress.json"
    output_path = tmp_path / "response.json"
    request_path = tmp_path / "request.json"
    prediction = {
        "crop_id": "BOUND_L01", "predicted_class": "sin_oleocelosis",
        "confidence": 0.95, "oleocellosis_probability": 0.05,
    }
    record = inference._record("BOUND", "capture", [prediction], {})
    monkeypatch.setattr(inference, "_infer_crop_batch", lambda *args, **kwargs: [record])
    write = inference._atomic_json

    def locked_progress(path, content):
        if path == progress_path:
            raise PermissionError("WinError5: el progreso está bloqueado")
        write(path, content)

    monkeypatch.setattr(inference, "_atomic_json", locked_progress)
    request_path.write_text(json.dumps({
        "images": [{"path": "fruit.jpg", "image_id": "BOUND", "input_kind": "fruit_crop"}],
        "progress_path": str(progress_path),
    }), encoding="utf-8")
    assert inference.main(["--request", str(request_path), "--output", str(output_path)]) == 0
    assert json.loads(output_path.read_text("utf-8"))["records"] == [record]


def test_locked_final_response_reports_failure_clearly(tmp_path, monkeypatch, capsys):
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "response.json"
    monkeypatch.setattr(inference, "run_request", lambda request: {"records": []})

    def locked(path, content):
        raise PermissionError("WinError5: resultado bloqueado")

    monkeypatch.setattr(inference, "_atomic_json", locked)
    request_path.write_text('{"images": []}', encoding="utf-8")
    assert inference.main(["--request", str(request_path), "--output", str(output_path)]) == 1
    assert "No se pudo guardar el resultado de Vision" in capsys.readouterr().err
