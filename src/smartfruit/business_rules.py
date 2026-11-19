"""Business Severity rules copied from the existing SmartFruit integration.

Only the eight defects in ``BUSINESS_DEFECT_MAP`` are evaluated here.  Input
percentages use the 0–100 scale; missing observations never imply zero.
"""

import math
from collections.abc import Mapping
from copy import deepcopy

RULES_ENGINE_VERSION = "2.0.0"

BUSINESS_DEFECT_MAP = {
    "scars_pct": {
        "business_name": "Cicatrices / defectos de piel",
        "group": "quality",
        "rule": "quality_5_20",
    },
    "blanching_pct": {
        "business_name": "Blanqueamiento / decoloración",
        "group": "quality",
        "rule": "quality_5_20",
    },
    "yellow_color_pct": {
        "business_name": "Color amarillo / sobremaduro",
        "group": "quality",
        "rule": "quality_5_20",
    },
    "oleocellosis_pct": {
        "business_name": "Oleocelosis",
        "group": "condition",
        "rule": "condition_5_10",
    },
    "styler_pct": {
        "business_name": "Styler (limes)",
        "group": "condition",
        "rule": "condition_5_10",
    },
    "skin_breakdown_pct": {
        "business_name": "Skin Breakdown / Fumigation Damage",
        "group": "condition",
        "rule": "skin_breakdown_0_5",
    },
    "mold_pct": {
        "business_name": "Moho",
        "group": "condition",
        "rule": "mold_decay_0_1",
    },
    "decay_pct": {
        "business_name": "Pudrición",
        "group": "condition",
        "rule": "mold_decay_0_1",
    },
}


def _validate_boundary_policy(boundary_policy):
    if boundary_policy not in ("higher", "lower"):
        raise ValueError("boundary_policy debe ser 'higher' o 'lower'")


def _boundary_compare(value, threshold, boundary_policy):
    _validate_boundary_policy(boundary_policy)
    if boundary_policy == "higher":
        return value >= threshold
    return value > threshold


def business_level(value, rule, boundary_policy="higher"):
    """Return the existing rule's level, rejecting missing/invalid percentages.

    ``higher`` assigns exact boundaries to the higher level; ``lower`` keeps
    them at the lower level.  No operational threshold has been added.
    """
    _validate_boundary_policy(boundary_policy)
    if value is None or isinstance(value, bool):
        raise ValueError("Porcentaje de defecto debe ser un número observado entre 0 y 100")
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Porcentaje de defecto debe ser un número entre 0 y 100") from exc
    if not math.isfinite(x) or not 0 <= x <= 100:
        raise ValueError("Porcentaje de defecto debe ser finito y estar entre 0 y 100")

    if rule == "quality_5_20":
        if _boundary_compare(x, 20.0, boundary_policy):
            return 3
        if _boundary_compare(x, 5.0, boundary_policy):
            return 2
        return 1
    if rule == "condition_5_10":
        if _boundary_compare(x, 10.0, boundary_policy):
            return 3
        if _boundary_compare(x, 5.0, boundary_policy):
            return 2
        return 1
    if rule == "skin_breakdown_0_5":
        if _boundary_compare(x, 5.0, boundary_policy):
            return 3
        if x > 0:
            return 2
        return 1
    if rule == "mold_decay_0_1":
        if _boundary_compare(x, 1.0, boundary_policy):
            return 3
        if x > 0:
            return 2
        return 1
    raise ValueError(f"Regla no reconocida: {rule}")


def evaluate_business_severity(record, boundary_policy="higher"):
    """Evaluate all eight mapped defects without altering the source record.

    Existing thresholds and maximum-level reasons are retained.
    STANDARD gains a textual explanation of that same outcome.  Other QC
    columns remain outside this module's explicitly limited rule coverage.
    """
    _validate_boundary_policy(boundary_policy)
    if not isinstance(record, Mapping) or not isinstance(record.get("defects"), Mapping):
        raise ValueError("La inspección debe contener los defectos observados en 'defects'")

    defects_out = {}
    quality_levels, condition_levels = [], []
    for col, meta in BUSINESS_DEFECT_MAP.items():
        defect = record["defects"].get(col)
        if not isinstance(defect, Mapping) or "pct" not in defect:
            raise ValueError(f"Falta registrar el porcentaje de {meta['business_name']} ({col})")
        try:
            level = business_level(defect["pct"], meta["rule"], boundary_policy)
        except ValueError as exc:
            raise ValueError(f"{meta['business_name']} ({col}): {exc}") from exc
        result = deepcopy(dict(defect))
        result["business_name"] = meta["business_name"]
        result["group"] = meta["group"]
        result["business_level"] = level
        defects_out[col] = result
        (quality_levels if meta["group"] == "quality" else condition_levels).append(level)

    max_level = max(quality_levels + condition_levels)
    reasons = [
        defect["business_name"]
        for defect in defects_out.values()
        if defect["business_level"] == max_level and max_level > 1
    ]
    if max_level == 1:
        reasons = ["Los ocho defectos con regla disponible se encuentran en Nivel 1."]

    out = deepcopy(dict(record))
    out["defects"] = defects_out
    out["business_severity"] = {
        "rules_engine_version": RULES_ENGINE_VERSION,
        "boundary_policy": boundary_policy,
        "quality_max_level": max(quality_levels),
        "condition_max_level": max(condition_levels),
        "business_max_level": max_level,
        "recommendation": {1: "STANDARD", 2: "EXTEND", 3: "EXTEND"}[max_level],
        "reasons": reasons,
    }
    return out
