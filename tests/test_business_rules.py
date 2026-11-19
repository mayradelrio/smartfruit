"""Boundary and compatibility checks against the unchanged integration rules."""

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

from smartfruit.business_rules import (
    BUSINESS_DEFECT_MAP,
    business_level,
    evaluate_business_severity,
)


@pytest.fixture(scope="module")
def legacy_rules():
    path = Path(__file__).resolve().parents[1] / "legacy/integration/smartfruit_integration_v1.py"
    spec = importlib.util.spec_from_file_location("legacy_business_rules", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observed_record(**values):
    return {
        "sample_id": "SAMPLE_TEST",
        "defects": {
            key: {
                "business_name": meta["business_name"],
                "group": meta["group"],
                "source": "vision_ai" if key == "oleocellosis_pct" else "qc_manual",
                "pct": values.get(key, 0.0),
            }
            for key, meta in BUSINESS_DEFECT_MAP.items()
        },
    }


@pytest.mark.parametrize(
    "rule,value,higher,lower",
    [
        ("quality_5_20", 0, 1, 1),
        ("quality_5_20", 4.9999, 1, 1),
        ("quality_5_20", 5, 2, 1),
        ("quality_5_20", 5.0001, 2, 2),
        ("quality_5_20", 19.9999, 2, 2),
        ("quality_5_20", 20, 3, 2),
        ("quality_5_20", 20.0001, 3, 3),
        ("condition_5_10", 0, 1, 1),
        ("condition_5_10", 4.9999, 1, 1),
        ("condition_5_10", 5, 2, 1),
        ("condition_5_10", 5.0001, 2, 2),
        ("condition_5_10", 9.9999, 2, 2),
        ("condition_5_10", 10, 3, 2),
        ("condition_5_10", 10.0001, 3, 3),
        ("skin_breakdown_0_5", 0, 1, 1),
        ("skin_breakdown_0_5", 0.0001, 2, 2),
        ("skin_breakdown_0_5", 4.9999, 2, 2),
        ("skin_breakdown_0_5", 5, 3, 2),
        ("skin_breakdown_0_5", 5.0001, 3, 3),
        ("mold_decay_0_1", 0, 1, 1),
        ("mold_decay_0_1", 0.0001, 2, 2),
        ("mold_decay_0_1", 0.9999, 2, 2),
        ("mold_decay_0_1", 1, 3, 2),
        ("mold_decay_0_1", 1.0001, 3, 3),
        ("mold_decay_0_1", 100, 3, 3),
    ],
)
def test_rule_boundaries(rule, value, higher, lower):
    assert business_level(value, rule, "higher") == higher
    assert business_level(value, rule, "lower") == lower


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        -0.01,
        100.01,
        float("nan"),
        float("inf"),
        -float("inf"),
        "",
        "pendiente",
        [],
        {},
    ],
)
def test_reject_missing_invalid_or_out_of_domain_percentage(value):
    with pytest.raises(ValueError, match="Porcentaje"):
        business_level(value, "condition_5_10")


@pytest.mark.parametrize(
    "rule", ["quality_5_20", "condition_5_10", "skin_breakdown_0_5", "mold_decay_0_1"]
)
def test_invalid_boundary_policy_is_rejected_even_at_zero(rule):
    with pytest.raises(ValueError, match="boundary_policy"):
        business_level(0, rule, "unknown")


def test_unknown_rule_is_rejected():
    with pytest.raises(ValueError, match="Regla no reconocida"):
        business_level(0, "unmapped_defect")


@pytest.mark.parametrize(
    "values,expected,level,reasons",
    [
        ({}, "STANDARD", 1, ["Los ocho defectos con regla disponible se encuentran en Nivel 1."]),
        ({"oleocellosis_pct": 8.3333}, "EXPAND", 2, ["Oleocelosis"]),
        ({"oleocellosis_pct": 8, "mold_pct": 1.5}, "ESCALATE", 3, ["Moho"]),
        (
            {"scars_pct": 21, "decay_pct": 2},
            "ESCALATE",
            3,
            ["Cicatrices / defectos de piel", "Pudrición"],
        ),
    ],
)
def test_recommendation_and_explained_maximum(values, expected, level, reasons):
    result = evaluate_business_severity(observed_record(**values))
    severity = result["business_severity"]
    assert severity["recommendation"] == expected
    assert severity["business_max_level"] == level
    assert severity["reasons"] == reasons


def test_group_levels_and_input_are_preserved():
    source = observed_record(scars_pct=7, decay_pct=2)
    source["metadata"] = {"trace": ["original"]}
    before = deepcopy(source)
    result = evaluate_business_severity(source)
    assert source == before
    assert result["business_severity"]["quality_max_level"] == 2
    assert result["business_severity"]["condition_max_level"] == 3
    result["defects"]["scars_pct"]["pct"] = 99
    result["metadata"]["trace"].append("changed")
    assert source == before


@pytest.mark.parametrize("key", list(BUSINESS_DEFECT_MAP))
@pytest.mark.parametrize("missing", ["defect", "pct", "value"])
def test_no_default_zero_for_unrecorded_observations(key, missing):
    record = observed_record()
    if missing == "defect":
        del record["defects"][key]
    elif missing == "pct":
        del record["defects"][key]["pct"]
    else:
        record["defects"][key]["pct"] = None
    with pytest.raises(ValueError, match=key):
        evaluate_business_severity(record)


@pytest.mark.parametrize("record", [None, {}, {"defects": None}, {"defects": []}])
def test_reject_malformed_inspection(record):
    with pytest.raises(ValueError, match="defects"):
        evaluate_business_severity(record)


def test_business_defect_map_matches_unchanged_legacy(legacy_rules):
    assert BUSINESS_DEFECT_MAP == legacy_rules.BUSINESS_DEFECT_MAP


@pytest.mark.parametrize("policy", ["higher", "lower"])
def test_valid_rule_outputs_match_legacy_across_domain(legacy_rules, policy):
    values = [
        0,
        0.0001,
        0.9999,
        1,
        1.0001,
        4.9999,
        5,
        5.0001,
        9.9999,
        10,
        10.0001,
        19.9999,
        20,
        20.0001,
        100,
    ]
    for rule in {meta["rule"] for meta in BUSINESS_DEFECT_MAP.values()}:
        for value in values:
            assert business_level(value, rule, policy) == legacy_rules.business_level(
                value, rule, policy
            )


@pytest.mark.parametrize("policy", ["higher", "lower"])
def test_evaluation_matches_legacy_except_standard_explanation(legacy_rules, policy):
    for record in [
        observed_record(),
        observed_record(scars_pct=5, oleocellosis_pct=10),
        observed_record(mold_pct=1, decay_pct=1),
    ]:
        expected = legacy_rules.evaluate_business_severity(record, policy)
        actual = evaluate_business_severity(record, policy)
        if expected["business_severity"]["business_max_level"] == 1:
            expected["business_severity"]["reasons"] = actual["business_severity"]["reasons"]
        assert actual == expected
