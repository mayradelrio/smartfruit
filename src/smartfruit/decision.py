"""Recomendación existente y confirmación explícita del inspector."""

from copy import deepcopy
from datetime import datetime, timezone

RECOMMENDATIONS = ("STANDARD", "EXPAND", "ESCALATE")


def build_final_report(record):
    severity = record["business_severity"]
    report = {
        "schema_version": record.get("schema_version", "1.0"),
        "lot_id": record.get("lot_id"),
        "pallet_id": record.get("pallet_id"),
        "sample_id": record["sample_id"],
        "inspection_summary": deepcopy(record["vision_summary"]),
        "qc_fields": deepcopy(record["qc_fields"]),
        "defects": deepcopy(record["defects"]),
        "business_severity": deepcopy(severity),
        "predictive": deepcopy(record["predictive"]),
        "final_recommendation": severity["recommendation"],
        "recommendation_reasons": list(severity["reasons"]),
        "human_confirmation_required": True,
        "inspector_final_decision": None,
        "inspector_confirmed": False,
        "observations": record.get("observations", ""),
        "rule_coverage": deepcopy(record["rule_coverage"]),
    }
    if "reception" in record:
        report["reception"] = deepcopy(record["reception"])
    if "image_bindings" in record:
        report["image_bindings"] = deepcopy(record["image_bindings"])
    if "review_history" in record:
        report["review_history"] = deepcopy(record["review_history"])
    if "review_choice" in record:
        report["review_choice"] = record["review_choice"]
    for key in ("box_inspection", "box_inspections"):
        if key in record:
            report[key] = deepcopy(record[key])
    return report


def confirm_inspection(report, inspector_name, decisions, confirmed=False):
    if confirmed is not True:
        raise ValueError("Se requiere confirmación explícita del inspector.")
    if not isinstance(inspector_name, str) or not inspector_name.strip():
        raise ValueError("Completar el nombre del inspector para confirmar.")
    if report.get("lot_reception") and report.get("qc_header", {}).get("Level_Flag") in (None, ""):
        raise ValueError("Registrar el Level Flag final del inspector antes de cerrar el lote.")
    ids = {sample["sample_id"] for sample in report["samples"]}
    if not isinstance(decisions, dict) or set(decisions) != ids:
        raise ValueError("Registrar la decisión final del inspector para cada muestra.")
    decisions = {key: "EXPAND" if value == "EXTEND" else value for key, value in decisions.items()}
    if any(value not in RECOMMENDATIONS for value in decisions.values()):
        raise ValueError("La decisión final debe ser STANDARD, EXPAND o ESCALATE.")
    result = deepcopy(report)
    result["inspector_name"] = inspector_name.strip()
    result["inspector_confirmed"] = True
    result["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    for sample in result["samples"]:
        sample["inspector_final_decision"] = decisions[sample["sample_id"]]
        sample["inspector_confirmed"] = True
    return result
