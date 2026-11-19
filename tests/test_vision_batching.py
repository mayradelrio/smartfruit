"""Batched crop inference with real image decoding and a bounded fake classifier."""

import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image

from smartfruit import vision_inference as inference
from smartfruit.vision import validate_vision_record


@pytest.fixture
def classifier(tmp_path, monkeypatch):
    calls = SimpleNamespace(batches=[], transforms=[], progress=[], invalid_token=None)
    classes = {"sin_oleocelosis": 0, "con_oleocelosis": 1}

    def transform(image):
        calls.transforms.append((image.mode, image.size))
        return image.getpixel((0, 0))[0]

    def model(batch):
        calls.batches.append(list(batch))
        return [
            [float("nan"), 0.5] if token == calls.invalid_token
            else [0.123456789, 0.876543211] if token % 2
            else [0.876543211, 0.123456789]
            for token in batch
        ]

    class Probabilities:
        def __init__(self, rows):
            self.rows = rows

        def cpu(self):
            return self

        def tolist(self):
            return self.rows

    torch = ModuleType("torch")
    torch.inference_mode = nullcontext
    torch.stack = lambda tensors: list(tensors)

    def softmax(logits, dim):
        assert dim == 1
        return Probabilities(logits)

    torch.softmax = softmax
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(inference, "get_runtime_status", lambda *args: {"ready": True})
    monkeypatch.setattr(inference, "_load_classifier", lambda signature: (model, transform, classes))
    monkeypatch.setattr(inference, "_load_detector", lambda *args: pytest.fail("No detector for crops"))
    monkeypatch.setattr(
        inference, "_write_progress", lambda path, completed, total: calls.progress.append((completed, total))
    )
    (tmp_path / inference.CLASSIFIER_FILENAME).write_bytes(b"stub; never loaded as weights")
    monkeypatch.delenv("SMARTFRUIT_VISION_BATCH_SIZE", raising=False)
    return calls


def images(tmp_path, count):
    result = []
    for index in range(count):
        path = tmp_path / f"fruit_{index:03}.png"
        Image.new("RGB", (3, 5), (index, 20, 30)).save(path)
        result.append({"path": str(path), "image_id": f"BOUND_{index:03}"})
    return result


def test_150_crops_use_five_forward_passes_and_preserve_record_order_precision(tmp_path, classifier):
    inputs = images(tmp_path, 150)
    inputs[7]["partition"] = "special-partition"
    result = inference.run_request({
        "images": inputs, "input_kind": "fruit_crop", "partition": "capture",
        "models_dir": str(tmp_path),
    })
    assert [len(batch) for batch in classifier.batches] == [32, 32, 32, 32, 22]
    assert classifier.progress == [(0, 150), (32, 150), (64, 150), (96, 150), (128, 150), (150, 150)]
    records = result["records"]
    assert [record["image_id"] for record in records] == [item["image_id"] for item in inputs]
    assert len(records) == 150
    for index, record in enumerate(records):
        validate_vision_record(record)
        assert record["partition"] == ("special-partition" if index == 7 else "capture")
        assert record["total_fruits"] == 1
        assert record["oleocellosis_count"] == index % 2
        assert record["fruit_predictions"][0]["crop_id"] == f"BOUND_{index:03}_L01.jpg"
        assert record["fruit_predictions"][0]["oleocellosis_probability"] == (
            0.876543211 if index % 2 else 0.123456789
        )
        assert record["inference"]["source_filename"] == Path(inputs[index]["path"]).name
        assert record["inference"]["class_to_idx"] == {"sin_oleocelosis": 0, "con_oleocelosis": 1}
        assert record["inference"]["image_size"] == [3, 5]
        assert record["inference"]["device"] == "cpu"


def test_mixed_requests_keep_scenes_on_existing_path_and_results_in_input_order(
    tmp_path, classifier, monkeypatch,
):
    crops = images(tmp_path, 5)
    calls = []

    def scene(path, **kwargs):
        calls.append((path, kwargs))
        assert kwargs["input_kind"] == "scene"
        return inference._record(kwargs["image_id"], kwargs["partition"], [], {"input_kind": "scene"})

    monkeypatch.setattr(inference, "infer_image", scene)
    inputs = [crops[0], crops[1], {"path": "scene-a.jpg", "image_id": "SCENE_A", "input_kind": "scene"},
              *crops[2:], {"path": "scene-b.jpg", "image_id": "SCENE_B", "input_kind": "scene"}]
    result = inference.run_request({
        "images": inputs, "input_kind": "fruit_crop", "models_dir": str(tmp_path), "batch_size": 2,
    })
    assert [record["image_id"] for record in result["records"]] == [item["image_id"] for item in inputs]
    assert [len(batch) for batch in classifier.batches] == [2, 2, 1]
    assert [kwargs["image_id"] for _, kwargs in calls] == ["SCENE_A", "SCENE_B"]
    assert classifier.progress == [(0, 7), (2, 7), (3, 7), (5, 7), (6, 7), (7, 7)]


def test_batch_crop_matches_standalone_exif_and_rgb_contract(tmp_path, classifier):
    path = tmp_path / "oriented.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("L", (3, 5), 20).save(path, exif=exif)
    batched = inference.run_request({"images": [{"path": str(path)}], "input_kind": "fruit_crop",
                                     "models_dir": str(tmp_path)})["records"][0]
    standalone = inference.infer_image(path, input_kind="fruit_crop", models_dir=tmp_path)
    assert batched == standalone
    assert batched["inference"]["image_size"] == [5, 3]
    assert classifier.transforms == [("RGB", (5, 3)), ("RGB", (5, 3))]


def test_batch_size_environment_and_request_override(tmp_path, classifier, monkeypatch):
    inputs = images(tmp_path, 5)
    monkeypatch.setenv("SMARTFRUIT_VISION_BATCH_SIZE", " 2 ")
    inference.run_request({"images": inputs, "input_kind": "fruit_crop", "models_dir": str(tmp_path)})
    assert [len(batch) for batch in classifier.batches] == [2, 2, 1]
    classifier.batches.clear()
    monkeypatch.setenv("SMARTFRUIT_VISION_BATCH_SIZE", "invalid")
    inference.run_request({"images": inputs, "input_kind": "fruit_crop", "models_dir": str(tmp_path),
                           "batch_size": 4})
    assert [len(batch) for batch in classifier.batches] == [4, 1]


@pytest.mark.parametrize("batch_size, sizes", [(1, [1] * 5), (128, [5])])
def test_supported_batch_size_boundaries_preserve_all_inputs(tmp_path, classifier, batch_size, sizes):
    result = inference.run_request({
        "images": images(tmp_path, 5), "input_kind": "fruit_crop", "models_dir": str(tmp_path),
        "batch_size": batch_size,
    })
    assert [len(batch) for batch in classifier.batches] == sizes
    assert len(result["records"]) == 5


@pytest.mark.parametrize("value", [0, -1, 129, True, False, 1.5, "32", None])
def test_invalid_request_batch_size_is_rejected_before_inference(tmp_path, classifier, value):
    with pytest.raises(ValueError, match="batch_size"):
        inference.run_request({"images": [{"path": "not-read.png"}], "batch_size": value})
    assert classifier.batches == []


@pytest.mark.parametrize("value", ["", "0", "-1", "129", "1.5", "true", "٣٢"])
def test_invalid_environment_batch_size_is_rejected(classifier, monkeypatch, value):
    monkeypatch.setenv("SMARTFRUIT_VISION_BATCH_SIZE", value)
    with pytest.raises(ValueError, match="SMARTFRUIT_VISION_BATCH_SIZE"):
        inference.run_request({"images": [{"path": "not-read.png"}]})
    assert classifier.batches == []


def test_batch_failure_returns_only_an_error_and_never_publishes_partial_records(
    tmp_path, classifier, monkeypatch,
):
    inputs = images(tmp_path, 150)
    classifier.invalid_token = 149
    progress = []
    monkeypatch.setattr(inference, "_write_progress", lambda path, done, total: progress.append((done, total)))
    request = tmp_path / "request.json"
    response = tmp_path / "response.json"
    request.write_text(json.dumps({"images": inputs, "input_kind": "fruit_crop", "models_dir": str(tmp_path)}), "utf-8")
    assert inference.main(["--request", str(request), "--output", str(response)]) == 1
    result = json.loads(response.read_text("utf-8"))
    assert set(result) == {"error"}
    assert "probabilidades" in result["error"]
    assert progress[-1] == (128, 150)


def test_corrupt_image_stops_batch_without_returning_fabricated_results(tmp_path, classifier):
    inputs = images(tmp_path, 3)
    Path(inputs[-1]["path"]).write_bytes(b"not an image")
    with pytest.raises(ValueError, match="No se pudo abrir la imagen"):
        inference.run_request({"images": inputs, "input_kind": "fruit_crop", "models_dir": str(tmp_path)})
    assert classifier.batches == []
    assert classifier.progress == [(0, 3)]


def test_missing_classifier_output_cannot_silently_drop_a_photo(tmp_path, classifier, monkeypatch):
    _, transform, classes = inference._load_classifier(("unused", 0, 0))
    monkeypatch.setattr(inference, "_load_classifier", lambda signature: (
        lambda batch: [[0.9, 0.1]], transform, classes,
    ))
    with pytest.raises(ValueError, match="una predicción por fotografía"):
        inference.run_request({"images": images(tmp_path, 2), "input_kind": "fruit_crop",
                               "models_dir": str(tmp_path)})
    assert classifier.progress == [(0, 2)]
