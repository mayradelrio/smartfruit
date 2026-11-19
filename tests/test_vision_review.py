"""Raw positives require QC and remain auditable after false-positive correction."""

from copy import deepcopy

import pytest

from smartfruit.vision import aggregate_vision_sample, load_vision_json
from smartfruit.vision_review import initialize_vision_review, review_vision_prediction
from smartfruit.vision_validation import build_adjudicated_dataset, calculate_vision_metrics
from smartfruit.workflow import evaluate_inspection


def raw_record():
    return {
        "image_id": "GROUP_1", "partition": "test", "total_fruits": 4,
        "oleocellosis_count": 2, "oleocellosis_pct": 50, "mean_confidence": 0.9,
        "inference": {"input_kind": "scene", "source_filename": "group.jpg"},
        "fruit_predictions": [{
            "crop_id": f"FRUIT_{index}",
            "predicted_class": "con_oleocelosis" if index < 2 else "sin_oleocelosis",
            "oleocellosis_probability": 0.9 if index < 2 else 0.1,
            "confidence": 0.9,
        } for index in range(4)],
    }


def reviewed():
    result = review_vision_prediction(raw_record(), "FRUIT_0", "confirmed", "Inspector QC")
    return review_vision_prediction(
        result, "FRUIT_1", "rejected", "Inspector QC", override_label="styler",
        override_reason="Defecto styler observado por QC",
    )


def test_historical_positive_is_pending_and_never_an_operational_count():
    source = raw_record()
    original = deepcopy(source)
    loaded = load_vision_json(source)
    assert loaded == source == original
    initialized = initialize_vision_review(source)
    assert initialized["fruit_predictions"][0]["review_status"] == "pending"
    assert initialized["fruit_predictions"][0]["reviewed_by"] is None
    summary = aggregate_vision_sample([source], "S")["vision_summary"]
    assert summary["raw_oleocellosis_count"] == 2
    assert summary["suspected_oleocellosis_count"] == 2
    assert summary["confirmed_oleocellosis_count"] == summary["oleocellosis_count"] == 0
    assert summary["pending_review_count"] == 2
    assert summary["review_completed"] is False
    assert summary["vision_review"][0]["review_status"] == "pending"


@pytest.mark.parametrize("included", [True, False])
def test_checkbox_selection_stays_pending_until_qc_applies_it(included):
    source = raw_record()
    for prediction in source["fruit_predictions"][:2]:
        prediction["qc_included"] = included
    original = deepcopy(source)
    summary = aggregate_vision_sample([source], "S")["vision_summary"]
    assert summary["oleocellosis_count"] == 0
    assert summary["pending_review_count"] == 2
    assert summary["raw_oleocellosis_count"] == 2
    assert source == original


@pytest.mark.parametrize("included", [None, 0, 1, "true", [], {}])
def test_checkbox_selection_requires_an_explicit_boolean(included):
    source = raw_record()
    source["fruit_predictions"][0]["qc_included"] = included
    with pytest.raises(ValueError, match="qc_included"):
        load_vision_json(source)


@pytest.mark.parametrize("index,included", [(0, False), (1, True)])
def test_checkbox_cannot_contradict_an_applied_qc_review(index, included):
    source = reviewed()
    source["fruit_predictions"][index]["qc_included"] = included
    with pytest.raises(ValueError, match="qc_included"):
        load_vision_json(source)


def test_explicit_review_keeps_an_existing_checkbox_consistent_with_its_outcome():
    source = raw_record()
    source["fruit_predictions"][0]["qc_included"] = True
    excluded = review_vision_prediction(
        source, "FRUIT_0", "rejected", "QC", override_label="other",
        override_reason="Excluido por QC mediante el check de oleocelosis.",
    )
    assert excluded["fruit_predictions"][0]["qc_included"] is False
    restored = review_vision_prediction(excluded, "FRUIT_0", "confirmed", "QC")
    assert restored["fruit_predictions"][0]["qc_included"] is True
    assert restored["oleocellosis_count"] == source["oleocellosis_count"]
    assert restored["fruit_predictions"][0]["predicted_class"] == "con_oleocelosis"


def test_confirmed_counts_and_rejected_positive_preserves_original_and_override():
    source = raw_record()
    result = reviewed()
    summary = aggregate_vision_sample([result, deepcopy(result)], "S")["vision_summary"]
    assert summary["oleocellosis_count"] == 1
    assert summary["oleocellosis_pct"] == 25
    assert summary["raw_oleocellosis_count"] == 2
    assert summary["rejected_oleocellosis_count"] == 1
    assert summary["pending_review_count"] == 0 and summary["review_completed"]
    assert summary["total_fruits"] == 4
    assert result["oleocellosis_count"] == source["oleocellosis_count"] == 2
    rejected = result["fruit_predictions"][1]
    for field in ("predicted_class", "oleocellosis_probability", "confidence", "crop_id"):
        assert rejected[field] == source["fruit_predictions"][1][field]
    assert rejected["override_label"] == "styler"
    assert rejected["reviewed_by"] == "Inspector QC"
    assert rejected["reviewed_at"]
    assert result["inference"] == source["inference"]
    assert "styler" not in result  # A correction does not add another manual defect.


@pytest.mark.parametrize("label", ["styler", "scar", "inking", "clean", "other"])
def test_allowed_positive_override_labels(label):
    result = review_vision_prediction(
        raw_record(), "FRUIT_0", "rejected", "QC", override_label=label,
        override_reason="Corrección observada",
    )
    assert result["fruit_predictions"][0]["override_label"] == label


@pytest.mark.parametrize("changes", [
    {"review_status": "automatic"}, {"review_status": []},
    {"review_status": "confirmed", "reviewed_by": None},
    {"review_status": "confirmed", "reviewed_by": "QC", "reviewed_at": "bad"},
    {"review_status": "confirmed", "reviewed_by": "QC", "reviewed_at": "2026-11-18T10:00:00"},
    {"review_status": "pending", "reviewed_by": "QC"},
    {"review_status": "rejected", "reviewed_by": "QC", "reviewed_at": "2026-11-18T15:00:00Z"},
])
def test_malformed_or_incomplete_adjudication_is_rejected(changes):
    record = raw_record()
    record["fruit_predictions"][0].update(changes)
    with pytest.raises(ValueError):
        load_vision_json(record)


def test_reviewing_unknown_crop_or_non_positive_is_rejected():
    for crop in ("missing", "FRUIT_3"):
        with pytest.raises(ValueError):
            review_vision_prediction(raw_record(), crop, "confirmed", "QC")


def test_pending_and_confirmed_duplicate_cannot_silently_choose_one_review():
    source = raw_record()
    with pytest.raises(ValueError, match="contenido distinto"):
        aggregate_vision_sample([source, reviewed()], "S")


def test_rules_block_pending_and_never_recount_rejected_oleocellosis_as_styler():
    from smartfruit.inspection import MANUAL_DEFECTS

    payload = {
        "qc_header": {"lot_id": "LOT", "inspection_date": "2026-11-18", "Level_Flag": 3},
        "samples": [{
            "sample_id": "S", "pallet_id": "P", "vision_records": [raw_record()],
            "vision_covers_sample": True,
            "qc_fields": {column["key"]: 0 for column in MANUAL_DEFECTS},
        }],
    }
    with pytest.raises(ValueError, match="pendientes"):
        evaluate_inspection(payload)
    record = raw_record()
    for crop in ("FRUIT_0", "FRUIT_1"):
        record = review_vision_prediction(record, crop, "rejected", "QC", override_label="styler")
    payload["samples"][0]["vision_records"] = [record]
    report = evaluate_inspection(payload)
    sample = report["samples"][0]
    assert sample["qc_fields"]["oleocellosis"] == sample["qc_fields"]["styler"] == 0
    assert sample["final_recommendation"] == "STANDARD"
    assert sample["inspection_summary"]["raw_oleocellosis_count"] == 2
    assert report["qc_header"]["Level_Flag"] == 3


def test_metrics_use_adjudicated_labels_and_capture_false_negatives():
    records = [reviewed()]
    adjudications = [
        {"image_id": "GROUP_1", "crop_id": "FRUIT_2", "qc_final_label": "oleocellosis"},
        {"image_id": "GROUP_1", "crop_id": "FRUIT_3", "qc_final_label": "clean"},
    ]
    original = deepcopy(records)
    rows = build_adjudicated_dataset(records, adjudications)
    metrics = calculate_vision_metrics(rows)
    assert records == original
    assert metrics["confusion_matrix"]["values"] == [[1, 1], [1, 1]]
    assert metrics["precision"] == metrics["recall"] == metrics["f1"] == 0.5
    assert metrics["false_positives"] == metrics["false_negatives"] == 1
    assert metrics["adjudicated_count"] == 4 and metrics["complete"] is True
    assert metrics["adjudication_coverage"] == 1
    assert rows[1]["error_type"] == "oleocellosis -> styler"
    assert rows[2]["error_type"] == "false negative oleocellosis"
    assert "mean_confidence" not in metrics and "accuracy" not in metrics


def test_unadjudicated_negatives_are_excluded_not_reported_as_true_negatives():
    rows = build_adjudicated_dataset([reviewed()])
    metrics = calculate_vision_metrics(rows)
    assert metrics["true_negatives"] == 0
    assert metrics["pending_count"] == metrics["unreviewed_model_negatives"] == 2
    assert metrics["complete"] is False
    assert metrics["adjudication_coverage"] == 0.5
    assert "subset" in metrics["recall_scope"]


def test_empty_metrics_have_no_fabricated_performance():
    result = calculate_vision_metrics([])
    assert result["adjudicated_count"] == 0
    assert result["precision"] is result["recall"] is result["f1"] is None


def test_unknown_or_duplicate_adjudications_cannot_enter_measured_set():
    unknown = {"image_id": "GROUP_1", "crop_id": "missing", "qc_final_label": "clean"}
    with pytest.raises(ValueError, match="inexistente"):
        build_adjudicated_dataset([raw_record()], [unknown])
    unknown["crop_id"] = "FRUIT_0"
    with pytest.raises(ValueError, match="más de una vez"):
        build_adjudicated_dataset([raw_record()], [unknown, unknown])
    rows = build_adjudicated_dataset([reviewed()])
    with pytest.raises(ValueError, match="duplicada"):
        calculate_vision_metrics(rows + rows)
