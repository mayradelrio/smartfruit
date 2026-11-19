"""Agregación y validación de outputs existentes; no se ejecutan modelos."""

import io
import json
from copy import deepcopy
from pathlib import Path

import pytest

from smartfruit.vision import aggregate_vision_sample, load_vision_json, validate_vision_record

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "vision"


def record(image_id="IMG_A", total=2, affected=1, confidence=0.9):
    return {
        "image_id": image_id,
        "partition": "test",
        "total_fruits": total,
        "oleocellosis_count": affected,
        "oleocellosis_pct": 100 * affected / total if total else 0,
        "mean_confidence": confidence if total else None,
        "fruit_predictions": [
            {
                "crop_id": f"{image_id}_L{i:02d}.jpg",
                "predicted_class": "con_oleocelosis" if i < affected else "sin_oleocelosis",
                "confidence": confidence,
                "oleocellosis_probability": confidence if i < affected else 1 - confidence,
            }
            for i in range(total)
        ],
    }


def test_real_demo_and_duplicate_do_not_inflate_counts():
    paths = [EXAMPLES / f"IMG_{i}.json" for i in (6426, 6427, 6428)]
    result = aggregate_vision_sample(paths + [paths[0]], "SAMPLE_DEMO_001")
    summary = result["vision_summary"]
    assert summary["images_processed"] == 3
    assert summary["image_ids"] == ["IMG_6426", "IMG_6427", "IMG_6428"]
    assert summary["total_fruits"] == 36
    assert summary["oleocellosis_count"] == 3
    assert summary["oleocellosis_pct"] == pytest.approx(100 * 3 / 36)
    assert summary["mean_confidence"] == pytest.approx(0.9974216111111112)
    assert summary["duplicate_image_ids_ignored"] == ["IMG_6426"]


def test_weighted_percentage_and_confidence_are_based_on_fruits():
    first = record("SMALL", total=1, affected=1, confidence=0.6)
    second = record("LARGE", total=9, affected=0, confidence=1.0)
    summary = aggregate_vision_sample([first, second, first], "S")["vision_summary"]
    assert summary["oleocellosis_pct"] == 10
    assert summary["mean_confidence"] == pytest.approx(0.96)
    assert summary["low_confidence_count"] == 1
    assert summary["low_confidence_items"][0]["image_id"] == "SMALL"
    assert summary["low_confidence_items"][0]["crop_id"] == "SMALL_L00.jpg"


def test_percentage_is_not_rounded_before_rules():
    data = record(total=20001, affected=1000)
    percentage = aggregate_vision_sample([data], "S")["vision_summary"]["oleocellosis_pct"]
    assert percentage < 5
    assert percentage != round(percentage, 4)


def test_same_image_id_with_conflicting_content_is_rejected():
    first = record()
    changed = record(confidence=0.8)
    with pytest.raises(ValueError, match="mismo image_id con contenido distinto"):
        aggregate_vision_sample([first, changed], "S")


def test_loading_preserves_output_and_does_not_mutate_original():
    original = record()
    original["extra_metadata"] = {"unchanged": True}
    before = deepcopy(original)
    loaded = load_vision_json(original)
    assert loaded == original
    loaded["fruit_predictions"][0]["confidence"] = 0.1
    assert original == before
    assert load_vision_json(io.StringIO(json.dumps(before))) == before
    assert load_vision_json(json.dumps(before).encode()) == before


@pytest.mark.parametrize("field", list(record()))
def test_all_existing_contract_fields_are_required(field):
    data = record()
    del data[field]
    with pytest.raises(ValueError, match="faltan campos"):
        validate_vision_record(data)


@pytest.mark.parametrize("value", [True, -1, 1.5, "2", None])
@pytest.mark.parametrize("field", ["total_fruits", "oleocellosis_count"])
def test_invalid_counts_are_not_coerced(field, value):
    data = record()
    data[field] = value
    with pytest.raises(ValueError):
        validate_vision_record(data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.01, 100.01, True, "50"])
def test_invalid_percentages_are_rejected(value):
    data = record()
    data["oleocellosis_pct"] = value
    with pytest.raises(ValueError):
        validate_vision_record(data)


@pytest.mark.parametrize("field", ["confidence", "oleocellosis_probability"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.01, True, "0.9"])
def test_prediction_probability_and_confidence_domains(field, value):
    data = record()
    data["fruit_predictions"][0][field] = value
    with pytest.raises(ValueError):
        validate_vision_record(data)


def test_inconsistent_count_percentage_classes_and_crop_ids():
    cases = []
    data = record()
    data["oleocellosis_count"] = 3
    cases.append(data)
    data = record()
    data["oleocellosis_pct"] = 40
    cases.append(data)
    data = record()
    data["fruit_predictions"][0]["predicted_class"] = "sin_oleocelosis"
    cases.append(data)
    data = record()
    data["fruit_predictions"][0]["predicted_class"] = "otra_clase"
    cases.append(data)
    data = record()
    data["fruit_predictions"][1]["crop_id"] = data["fruit_predictions"][0]["crop_id"]
    cases.append(data)
    data = record()
    data["fruit_predictions"].pop()
    cases.append(data)
    for invalid in cases:
        with pytest.raises(ValueError):
            validate_vision_record(invalid)


@pytest.mark.parametrize(
    "field", ["crop_id", "predicted_class", "confidence", "oleocellosis_probability"]
)
def test_prediction_fields_are_required(field):
    data = record()
    del data["fruit_predictions"][0][field]
    with pytest.raises(ValueError, match="predicción sin campos"):
        validate_vision_record(data)


def test_empty_input_rejected_but_zero_fruits_record_is_explicit():
    with pytest.raises(ValueError, match="No hay JSON"):
        aggregate_vision_sample([], "S")
    summary = aggregate_vision_sample([record(total=0, affected=0)], "S")["vision_summary"]
    assert summary["total_fruits"] == 0
    assert summary["oleocellosis_pct"] == 0
    assert summary["mean_confidence"] is None


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), True])
def test_invalid_confidence_threshold_rejected(threshold):
    with pytest.raises(ValueError):
        aggregate_vision_sample([record()], "S", low_confidence_threshold=threshold)


def test_malformed_or_non_object_json_rejected():
    for source in (b"not-json", b"[]", b"null"):
        with pytest.raises(ValueError):
            load_vision_json(source)
