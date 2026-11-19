"""Recomendación existente y confirmación explícita del inspector."""

from copy import deepcopy
from datetime import datetime, timezone

from .business_rules import RULES_ENGINE_VERSION
from .defect_dominance import DEFECT_DOMINANCE, DOMINANCE_METADATA

RECOMMENDATIONS = ("STANDARD", "EXTEND", "COMPLETE")


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
        "final_recommendation": "COMPLETE" if record.get("review_history") else severity["recommendation"],
        "recommendation_reasons": list(severity["reasons"]),
        "human_confirmation_required": True,
        "inspector_final_decision": None,
        "inspector_confirmed": False,
        "observations": record.get("observations", ""),
        "rule_coverage": deepcopy(record["rule_coverage"]),
        "rules_engine_version": RULES_ENGINE_VERSION,
        "defect_dominance": {**deepcopy(DOMINANCE_METADATA), "priority": list(DEFECT_DOMINANCE)},
    }
    if "reception" in record:
        report["reception"] = deepcopy(record["reception"])
    if "image_bindings" in record:
        report["image_bindings"] = deepcopy(record["image_bindings"])
    if "review_history" in record:
        report["review_history"] = deepcopy(record["review_history"])
    if "review_choice" in record:
        report["review_choice"] = record["review_choice"]
    for key in ("box_inspection", "box_inspections", "inspection_status", "skip_reason", "selected_at", "completed_at"):
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
    decisions = {key: "EXTEND" if value == "EXPAND" else value for key, value in decisions.items()}
    if any(value not in RECOMMENDATIONS for value in decisions.values()):
        raise ValueError("La decisión debe ser STANDARD o EXTEND; la segunda caja queda COMPLETE.")
    for pallet in report.get("lot_reception", {}).get("pallets", []):
        if pallet["inspection_status"] not in ("COMPLETED", "SKIPPED"):
            raise ValueError("Completar u omitir las paletas pendientes antes de confirmar el reporte.")
    for sample in report["samples"]:
        choice = decisions[sample["sample_id"]]
        second_box = bool(sample.get("review_history", {}).get("additional"))
        if second_box and choice != "COMPLETE":
            raise ValueError("La segunda caja cierra la inspección con COMPLETE.")
        if not second_box and choice == "COMPLETE":
            raise ValueError("COMPLETE requiere haber completado la segunda caja.")
        if choice == "EXTEND":
            raise ValueError("Completar la segunda caja antes de confirmar una ampliación EXTEND.")
    result = deepcopy(report)
    result["inspector_name"] = inspector_name.strip()
    result["inspector_confirmed"] = True
    result["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    for sample in result["samples"]:
        sample["inspector_final_decision"] = decisions[sample["sample_id"]]
        sample["inspector_confirmed"] = True
    return result
