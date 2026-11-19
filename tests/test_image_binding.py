"""Importación atómica y asociación externa de fotografías a muestra/paleta/lote."""

from copy import deepcopy

import pytest

from smartfruit.image_binding import validate_image_bindings, validate_vision_import


def record(image_id="IMG-1", total=3, affected=1):
    return {
        "image_id": image_id,
        "partition": "test",
        "total_fruits": total,
        "oleocellosis_count": affected,
        "oleocellosis_pct": round(100 * affected / total, 4) if total else 0,
        "mean_confidence": 0.9 if total else None,
        "fruit_predictions": [
            {
                "crop_id": f"{image_id}_{i}",
                "predicted_class": "con_oleocelosis" if i < affected else "sin_oleocelosis",
                "confidence": 0.9,
                "oleocellosis_probability": 0.9 if i < affected else 0.1,
            }
            for i in range(total)
        ],
    }


def sample(sample_id="S-1", pallet_id="005824", records=None):
    return {
        "sample_id": sample_id,
        "pallet_id": pallet_id,
        "vision_records": records if records is not None else [],
    }


def payload(incoming=None, samples=None):
    return {
        "qc_header": {"lot_id": "LOT-1"},
        "sample_id": "S-1",
        "samples": samples if samples is not None else [sample()],
        "vision_records": incoming if incoming is not None else [record()],
    }


def binding(image_id="IMG-1", **changes):
    result = {
        "image_id": image_id,
        "sample_id": "S-1",
        "pallet_id": "005824",
        "lot_id": "LOT-1",
    }
    result.update(changes)
    return result


def reception(pallet_id="005824", lot_id="LOT-1"):
    return {
        "scan_input": pallet_id,
        "records": [
            {
                "scan_code": "ERP-LABEL",
                "lot_id": lot_id,
                "label_brand": "Example",
                "country_origin": "Example",
                "pallet_id": pallet_id,
                "size_declared": "150",
                "expected_count_per_box": "150",
            }
        ],
    }


def test_import_preserves_vision_and_binds_identity_outside_model_output():
    request = payload()
    original = deepcopy(request)
    result = validate_vision_import(request)
    assert request == original
    assert result["vision_records"] == original["vision_records"]
    assert result["image_bindings"] == [binding()]
    assert result["inspection_summary"]["total_fruits"] == 3
    assert result["inspection_summary"]["oleocellosis_pct"] == 100 / 3
    assert set(result["vision_records"][0]) == set(record())
    result["vision_records"][0]["fruit_predictions"][0]["confidence"] = 0.1
    result["image_bindings"][0]["pallet_id"] = "Changed"
    assert request == original


def test_identical_duplicates_same_target_are_retained_and_counted_only_once():
    first = record()
    second = record("IMG-2", total=2, affected=0)
    request = payload([first, second, first], [sample(records=[first])])
    result = validate_vision_import(request)
    assert len(result["vision_records"]) == 4
    assert result["image_bindings"] == [binding(), binding("IMG-2")]
    summary = result["inspection_summary"]
    assert summary["images_processed"] == 2
    assert summary["total_fruits"] == 5
    assert summary["oleocellosis_count"] == 1
    assert summary["oleocellosis_pct"] == 20
    assert summary["duplicate_image_ids_ignored"] == ["IMG-1", "IMG-1"]


@pytest.mark.parametrize("already_in_target", [False, True])
def test_conflicting_content_same_image_is_rejected_atomically(already_in_target):
    first = record()
    changed = deepcopy(first)
    changed["fruit_predictions"][0]["confidence"] = 0.8
    request = payload(
        [changed] if already_in_target else [first, changed],
        [sample(records=[first] if already_in_target else [])],
    )
    original = deepcopy(request)
    with pytest.raises(ValueError, match="contenido distinto"):
        validate_vision_import(request)
    assert request == original


def test_image_already_assigned_to_another_sample_is_rejected_even_if_identical():
    request = payload(samples=[sample(), sample("S-2", "P-2", [record()])])
    with pytest.raises(ValueError, match="otra muestra"):
        validate_vision_import(request)


def test_existing_cross_sample_assignment_is_rejected_before_any_import():
    request = payload(
        incoming=[],
        samples=[sample(records=[record()]), sample("S-2", "P-2", [record()])],
    )
    with pytest.raises(ValueError, match="otra muestra"):
        validate_vision_import(request)


@pytest.mark.parametrize("bad_record", [None, [], "/etc/passwd", b"{}", {"image_id": "BROKEN"}])
def test_whole_incoming_batch_is_validated_before_returning_anything(bad_record):
    request = payload([record(), bad_record])
    original = deepcopy(request)
    with pytest.raises(ValueError):
        validate_vision_import(request)
    assert request == original


def test_invalid_records_in_a_different_current_sample_also_reject_import():
    request = payload(samples=[sample(), sample("S-2", "P-2", [{"image_id": "BROKEN"}])])
    with pytest.raises(ValueError):
        validate_vision_import(request)


@pytest.mark.parametrize("key", ["sample_id", "pallet_id"])
def test_blank_sample_identity_rejected(key):
    request = payload()
    request["samples"][0][key] = " "
    with pytest.raises(ValueError, match=key):
        validate_vision_import(request)


def test_duplicate_sample_identity_rejected():
    request = payload(samples=[sample(), sample("S-2", "P-2")])
    request["samples"][1]["sample_id"] = request["samples"][0]["sample_id"]
    with pytest.raises(ValueError, match="sample_id repetido"):
        validate_vision_import(request)


def test_several_samples_can_belong_to_the_same_pallet():
    request = payload(samples=[sample(), sample("S-2", "005824", [record("OTHER-IMAGE")])])
    result = validate_vision_import(request)
    assert result["image_bindings"] == [binding()]
    assert result["inspection_summary"]["image_ids"] == ["IMG-1"]


def test_missing_target_or_lot_is_rejected_without_needing_qc_defects():
    request = payload()
    request["sample_id"] = "UNKNOWN"
    with pytest.raises(ValueError, match="no existe"):
        validate_vision_import(request)
    request = payload()
    request["qc_header"]["lot_id"] = ""
    with pytest.raises(ValueError, match="AgroPeru Lot Number"):
        validate_vision_import(request)


def test_empty_target_and_empty_batch_produce_no_summary_or_bindings():
    assert validate_vision_import(payload(incoming=[])) == {
        "vision_records": [],
        "inspection_summary": None,
        "image_bindings": [],
    }


def test_optional_reception_must_match_lot_pallet_and_all_source_rows():
    request = payload()
    request["samples"][0]["reception"] = reception()
    assert validate_vision_import(request)["image_bindings"] == [binding()]
    for incorrect in (
        reception(pallet_id="OTHER"),
        reception(lot_id="OTHER"),
        None,
    ):
        request["samples"][0]["reception"] = incorrect
        with pytest.raises(ValueError):
            validate_vision_import(request)
    mixed = reception()
    mixed["records"].extend(reception(pallet_id="OTHER")["records"])
    request["samples"][0]["reception"] = mixed
    with pytest.raises(ValueError, match="recepción no corresponde"):
        validate_vision_import(request)


def test_reception_cached_identity_cannot_disagree_with_source():
    request = payload()
    selection = reception()
    selection["lot_id"] = "OTHER"
    request["samples"][0]["reception"] = selection
    with pytest.raises(ValueError, match="lot_id de recepción"):
        validate_vision_import(request)


def test_existing_bindings_are_optional_but_validated_when_present():
    target = sample(records=[record()])
    target["image_bindings"] = [binding()]
    request = payload(incoming=[], samples=[target])
    assert validate_vision_import(request)["image_bindings"] == [binding()]
    target["image_bindings"][0]["lot_id"] = "OTHER"
    with pytest.raises(ValueError, match="lot_id"):
        validate_vision_import(request)


def test_binding_validation_deep_copies_and_accepts_duplicates_only_in_vision_records():
    associations = [binding()]
    result = validate_image_bindings(associations, [record(), record()], "S-1", "005824", "LOT-1")
    assert result == associations
    result[0]["sample_id"] = "Changed"
    assert associations == [binding()]
    assert validate_image_bindings([], [], "S-1", "005824", "LOT-1") == []


@pytest.mark.parametrize(
    "associations",
    [
        None,
        {},
        [],
        [binding(), binding()],
        [binding("OTHER")],
        [binding(lot_id="OTHER")],
        [binding(pallet_id="OTHER")],
        [binding(sample_id="OTHER")],
        [binding(extra="unexpected")],
        [{"image_id": "IMG-1"}],
        [binding(lot_id=None)],
    ],
)
def test_missing_duplicate_extra_or_drifting_bindings_rejected(associations):
    with pytest.raises(ValueError):
        validate_image_bindings(associations, [record()], "S-1", "005824", "LOT-1")


def test_qc_pallet_or_sample_lot_cannot_drift_from_association():
    request = payload()
    request["samples"][0]["qc_fields"] = {"pallet_id": "OTHER"}
    with pytest.raises(ValueError, match="N° PALLET"):
        validate_vision_import(request)
    del request["samples"][0]["qc_fields"]
    request["samples"][0]["lot_id"] = "OTHER"
    with pytest.raises(ValueError, match="lot_id"):
        validate_vision_import(request)


@pytest.mark.parametrize(
    "bad_payload",
    [None, [], {}, {"qc_header": None}, payload(samples=[]), {**payload(), "vision_records": None}],
)
def test_malformed_payloads_raise_value_error(bad_payload):
    with pytest.raises(ValueError):
        validate_vision_import(bad_payload)
