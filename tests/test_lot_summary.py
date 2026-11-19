"""Lot summaries describe observations and never infer a new severity policy."""

from copy import deepcopy

import pytest

from smartfruit.inspection import DEFECT_COLUMNS
from smartfruit.lot_summary import build_lot_summary


def sample(pallet_id, size, **counts):
    fields = {column["key"]: 0 for column in DEFECT_COLUMNS}
    fields.update(counts)
    fields.update(pallet_id=pallet_id, sample_count=size)
    return {"pallet_id": pallet_id, "qc_fields": fields}


def by_key(summary, key):
    return next(defect for defect in summary["defects"] if defect["key"] == key)


def test_weighted_percentages_and_reason_follow_quantities_not_mean_percentages():
    result = build_lot_summary(
        [sample("PALLET_A", 10, oleocellosis=2), sample("PALLET_B", 90, oleocellosis=3)]
    )
    oleo = by_key(result, "oleocellosis")
    assert result["pallet_count"] == 2
    assert result["sample_count"] == 100
    assert oleo == {
        "key": "oleocellosis",
        "label": "Oleocellosis",
        "count": 5,
        "pct": 5.0,
        "affected_pallets": 2,
        "inspected_pallets": 2,
        "min_count": 2,
        "max_count": 3,
    }
    assert result["total_defect_incidents"] == 5
    assert result["total_combined_pct"] == 5
    assert result["generated_reason"] == (
        "Up to 2 - 3 Oleocellosis in 2 of 2 pallets. Total 5 / 100 fruits (5%)."
    )


def test_legacy_multiple_samples_accumulate_per_pallet_before_ranges():
    result = build_lot_summary(
        [
            sample("PALLET_A", 10, scars=4),
            sample("PALLET_A", 30, scars=5),
            sample("PALLET_B", 60),
        ]
    )
    scars = by_key(result, "scars")
    assert result["pallet_count"] == 2
    assert result["sample_count"] == 100
    assert scars["count"] == 9
    assert scars["affected_pallets"] == 1
    assert scars["inspected_pallets"] == 2
    assert scars["min_count"] == scars["max_count"] == 9
    assert result["generated_reason"] == (
        "Up to 9 Scars in 1 of 2 pallets. Total 9 / 100 fruits (9%)."
    )


def test_all_zero_preserves_all_sixteen_defects_without_a_severity_claim():
    result = build_lot_summary([sample("PALLET_A", 10), sample("PALLET_B", 20)])
    assert [d["key"] for d in result["defects"]] == [c["key"] for c in DEFECT_COLUMNS]
    assert [d["label"] for d in result["defects"]] == [c["label"] for c in DEFECT_COLUMNS]
    assert len(result["defects"]) == 16
    assert all(d["count"] == d["pct"] == d["affected_pallets"] == 0 for d in result["defects"])
    assert all(d["min_count"] == d["max_count"] == 0 for d in result["defects"])
    assert result["total_defect_incidents"] == result["total_combined_pct"] == 0
    assert result["generated_reason"] == "No defects recorded in the inspected samples."
    assert result["level_flag_status"] == "INSPECTOR_REQUIRED"
    assert "Level_Flag" not in result
    assert "business_severity" not in result
    assert "final_recommendation" not in result


def test_manual_defects_without_severity_rules_are_included_in_totals_and_reason():
    result = build_lot_summary([sample("PALLET_A", 30, soft=2, white_stain=3, undersize=1)])
    assert by_key(result, "soft")["count"] == 2
    assert by_key(result, "white_stain")["count"] == 3
    assert by_key(result, "undersize")["count"] == 1
    assert result["total_defect_incidents"] == 6
    assert result["total_combined_pct"] == 20
    assert result["generated_reason"].splitlines() == [
        "Up to 2 Soft in 1 of 1 pallets. Total 2 / 30 fruits (6.6667%).",
        "Up to 3 White stain in 1 of 1 pallets. Total 3 / 30 fruits (10%).",
        "Up to 1 Undersize in 1 of 1 pallets. Total 1 / 30 fruits (3.3333%).",
    ]


def test_multiple_defect_incidents_are_not_capped_at_one_hundred_percent():
    counts = {column["key"]: 10 for column in DEFECT_COLUMNS}
    result = build_lot_summary([sample("PALLET_A", 10, **counts)])
    assert result["total_defect_incidents"] == 160
    assert result["total_combined_pct"] == 1600
    assert all(d["pct"] == 100 for d in result["defects"])


def test_summary_does_not_mutate_samples_or_embed_user_supplied_identifiers():
    source = [sample("=<script>alert(1)</script>", 3, black_tips=1)]
    source[0]["business_severity"] = {"business_max_level": 3, "recommendation": "ESCALATE"}
    before = deepcopy(source)
    result = build_lot_summary(source)
    assert source == before
    assert "<script>" not in result["generated_reason"]
    assert "ESCALATE" not in result["generated_reason"]
    assert result["generated_reason"] == (
        "Up to 1 Black tips in 1 of 1 pallets. Total 1 / 3 fruits (33.3333%)."
    )
    result["defects"][0]["count"] = 999
    assert source == before


@pytest.mark.parametrize("key", [c["key"] for c in DEFECT_COLUMNS])
def test_missing_observation_is_never_interpreted_as_zero(key):
    row = sample("PALLET_A", 10)
    del row["qc_fields"][key]
    with pytest.raises(ValueError):
        build_lot_summary([row])


@pytest.mark.parametrize("value", [None, "", "0", True, -1, 11, 1.5, float("nan"), {}])
def test_invalid_or_excessive_counts_are_rejected(value):
    with pytest.raises(ValueError):
        build_lot_summary([sample("PALLET_A", 10, soft=value)])


@pytest.mark.parametrize("value", [None, "", "10", True, 0, -1, 1.5, float("inf"), []])
def test_invalid_or_empty_sample_size_is_rejected(value):
    row = sample("PALLET_A", 10)
    row["qc_fields"]["sample_count"] = value
    with pytest.raises(ValueError):
        build_lot_summary([row])


@pytest.mark.parametrize("rows", [[], None, {}, "samples", [None], [{"pallet_id": "A"}]])
def test_empty_or_malformed_samples_are_rejected(rows):
    with pytest.raises(ValueError):
        build_lot_summary(rows)


def test_pallet_identification_must_be_complete_and_consistent():
    for pallet_id in (None, "", " ", 123, {}):
        with pytest.raises(ValueError):
            build_lot_summary([sample(pallet_id, 10)])
    row = sample("PALLET_A", 10)
    row["qc_fields"]["pallet_id"] = "PALLET_B"
    with pytest.raises(ValueError, match="no coincide"):
        build_lot_summary([row])


def test_positive_percentage_does_not_display_as_zero_after_rounding():
    result = build_lot_summary([sample("PALLET_A", 100_000_000, soft=1)])
    assert by_key(result, "soft")["pct"] > 0
    assert "(0%)." not in result["generated_reason"]
