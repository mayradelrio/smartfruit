"""No sumar JSON históricos de una foto y nuevos resultados de sus recortes."""

from copy import deepcopy

import pytest

from smartfruit.image_binding import validate_vision_import
from smartfruit.inspection import MANUAL_DEFECTS
from smartfruit.vision import aggregate_vision_sample
from smartfruit.workflow import evaluate_inspection


def _record(image_id, source_filename=None, input_kind="fruit_crop"):
    result = {
        "image_id": image_id, "partition": "capture", "total_fruits": 1,
        "oleocellosis_count": 0, "oleocellosis_pct": 0, "mean_confidence": 0.9,
        "fruit_predictions": [{
            "crop_id": image_id + "_L01", "predicted_class": "sin_oleocelosis",
            "confidence": 0.9, "oleocellosis_probability": 0.1,
        }],
    }
    if source_filename is not None:
        result["inference"] = {"source_filename": source_filename, "input_kind": input_kind}
    return result


def _sample(identifier, records):
    return {
        "sample_id": identifier, "pallet_id": identifier,
        "vision_records": records, "vision_covers_sample": True,
        "qc_fields": {column["key"]: 0 for column in MANUAL_DEFECTS},
    }


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("source_filename,input_kind", [
    ("IMG_6426_L01.jpg", "fruit_crop"),
    ("img_6426.JPG", "scene"),
])
def test_aggregate_rejects_legacy_and_new_results_for_same_fruit(
    reverse, source_filename, input_kind
):
    records = [
        _record("IMG_6426"),
        _record("PHOTO_HASH_A", source_filename, input_kind),
    ]
    if reverse:
        records.reverse()
    with pytest.raises(ValueError, match="comparten frutos"):
        aggregate_vision_sample(records, "SAMPLE")


def test_different_crops_of_one_photo_still_sum_and_identical_duplicate_is_ignored():
    first = _record("PHOTO_HASH_A", "IMG_6426_L01.jpg")
    second = _record("PHOTO_HASH_B", "IMG_6426_L02.jpg")
    summary = aggregate_vision_sample([first, second, deepcopy(first)], "SAMPLE")["vision_summary"]
    assert summary["total_fruits"] == 2
    assert summary["images_processed"] == 2
    assert summary["duplicate_image_ids_ignored"] == [first["image_id"]]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("additional", [False, True])
def test_import_rejects_overlap_across_pallets_and_additional_reviews(reverse, additional):
    legacy = _record("IMG_6426")
    generated = _record("PHOTO_HASH_A", "IMG_6426_L01.jpg")
    existing, incoming = (generated, legacy) if reverse else (legacy, generated)
    payload = {
        "qc_header": {"lot_id": "LOT"}, "sample_id": "SECOND",
        "samples": [_sample("FIRST", [existing]), _sample("SECOND", [])],
        "vision_records": [incoming],
    }
    original = deepcopy(payload)
    with pytest.raises(ValueError, match="comparten frutos"):
        validate_vision_import(payload, additional_review=additional)
    assert payload == original


def test_evaluate_cannot_bypass_overlap_check_by_skipping_import():
    payload = {
        "qc_header": {"lot_id": "LOT", "inspection_date": "2026-11-15", "Level_Flag": 1},
        "samples": [
            _sample("FIRST", [_record("IMG_6426")]),
            _sample("SECOND", [_record("PHOTO_HASH_A", "IMG_6426_L01.jpg")]),
        ],
    }
    with pytest.raises(ValueError, match="comparten frutos"):
        evaluate_inspection(payload)


def test_recrop_of_same_named_fruit_is_rejected_even_with_a_new_content_id():
    records = [
        _record("PHOTO_HASH_A", "IMG_6426_L01.jpg"),
        _record("PHOTO_HASH_B", "IMG_6426_L01.jpg"),
    ]
    with pytest.raises(ValueError, match="comparten frutos"):
        aggregate_vision_sample(records, "SAMPLE")
