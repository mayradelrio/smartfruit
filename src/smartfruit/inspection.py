"""Captura QC con los nombres existentes del parser de los reportes reales."""

import math
from copy import deepcopy
from datetime import date

from .box_inspection import summarize_box_inspection
from .business_rules import BUSINESS_DEFECT_MAP
from .image_binding import validate_image_bindings
from .reception import resolve_reception
from .vision import aggregate_vision_sample

# Orden y etiquetas de A15:AB15 de la hoja Report, sin AC (total calculado).
QC_COLUMNS = [
    {"key": "label_brand", "label": "Label", "group": "General Information"},
    {"key": "pallet_id", "label": "N° PALLET", "group": "General Information"},
    {"key": "grower", "label": "Grower", "group": "General Information"},
    {"key": "packing_date", "label": "Packing date", "group": "General Information"},
    {"key": "size", "label": "Size", "group": "General Information"},
    {
        "key": "avg_count_per_box",
        "label": "Avg. Count per Box.",
        "group": "General Information",
        "type": "number",
    },
    {"key": "plu_pct", "label": "PLU (%)", "group": "General Information"},
    {"key": "plu_coo", "label": "PLU/Coo", "group": "General Information"},
    {"key": "sample_count", "label": "Sample", "group": "General Information", "type": "number"},
    {"key": "open_rating", "label": "Open Rating", "group": "Condition"},
    {"key": "color_rating", "label": "Color Rating", "group": "Condition"},
    {"key": "pulp_temp", "label": "Pulp", "group": "Condition", "type": "number"},
    {"key": "decay", "label": "Decay", "group": "Condition", "type": "number"},
    {"key": "styler", "label": "Styler", "group": "Condition", "type": "number"},
    {"key": "mold", "label": "Mold", "group": "Condition", "type": "number"},
    {"key": "soft", "label": "Soft", "group": "Condition", "type": "number"},
    {"key": "skin_breakdown", "label": "Skin breakdown", "group": "Condition", "type": "number"},
    {"key": "oleocellosis", "label": "Oleocellosis", "group": "Condition", "type": "number"},
    {"key": "wounds", "label": "Wounds", "group": "Condition", "type": "number"},
    {"key": "int_dryness", "label": "Int. Dryness", "group": "Condition", "type": "number"},
    {"key": "black_tips", "label": "Black tips", "group": "Condition", "type": "number"},
    {"key": "skin_defect", "label": "Skin defect", "group": "Quality", "type": "number"},
    {"key": "scars", "label": "Scars", "group": "Quality", "type": "number"},
    {"key": "white_stain", "label": "White stain", "group": "Quality", "type": "number"},
    {"key": "blanching", "label": "Blanching", "group": "Quality", "type": "number"},
    {"key": "yellow_color", "label": "Yellow color", "group": "Quality", "type": "number"},
    {"key": "stain", "label": "Stain", "group": "Quality", "type": "number"},
    {"key": "undersize", "label": "Undersize", "group": "Quality", "type": "number"},
]
DEFECT_COLUMNS = QC_COLUMNS[12:]
MANUAL_DEFECTS = [c for c in DEFECT_COLUMNS if c["key"] != "oleocellosis"]
RULE_COVERAGE = {
    "evaluated": [c["label"] for c in DEFECT_COLUMNS if c["key"] + "_pct" in BUSINESS_DEFECT_MAP],
    "not_evaluated": [
        c["label"] for c in DEFECT_COLUMNS if c["key"] + "_pct" not in BUSINESS_DEFECT_MAP
    ],
}
HEADER_FIELDS = [
    {"key": "inspection_date", "label": "Inspection Date", "type": "date"},
    {"key": "vessel", "label": "Vessel"},
    {"key": "container", "label": "Container"},
    {"key": "lot_id", "label": "AgroPeru Lot Number"},
    {"key": "country_origin", "label": "Country Of Origin"},
    {"key": "remarks", "label": "Remarks"},
    {"key": "Level_Flag", "label": "Level Flag"},
    {"key": "reason", "label": "Reason"},
    {"key": "grade", "label": "Grade"},
    {"key": "color", "label": "Color"},
    {"key": "plu_pct", "label": "PLU%"},
]

QC_SUMMARY_FIELDS = [
    {"key": "label_brand", "label": "Label"},
    {"key": "packing_date", "label": "Packing date"},
    {"key": "plu_coo", "label": "PLU/Coo"},
    {"key": "open_rating", "label": "Open Rating"},
    {"key": "color_rating", "label": "Color Rating"},
]


def validate_qc_summary(summary):
    if not isinstance(summary, dict):
        raise ValueError("El resumen QC debe contener los campos del renglón de totales.")
    result = {}
    for field in QC_SUMMARY_FIELDS:
        value = summary.get(field["key"], "")
        if value is None:
            value = ""
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError(f"Resumen QC: valor inválido para {field['label']}.")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"Resumen QC: valor no finito para {field['label']}.")
        result[field["key"]] = value
    return result


def identifier(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: debe completarse un identificador de texto.")
    return value.strip()


def _count(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"{label}: registrar una cantidad entera no negativa; pendiente no equivale a 0."
        )
    return value


def validate_header(header):
    if not isinstance(header, dict):
        raise ValueError("Falta la cabecera QC.")
    result = {field["key"]: header.get(field["key"], "") for field in HEADER_FIELDS}
    result["lot_id"] = identifier(result["lot_id"], "AgroPeru Lot Number")
    try:
        date.fromisoformat(result["inspection_date"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Inspection Date: usar una fecha válida AAAA-MM-DD.") from exc
    for key, value in result.items():
        if value is None:
            result[key] = ""
        elif not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError(f"Cabecera QC: valor inválido para {key}.")
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"Cabecera QC: valor no finito para {key}.")
    # Level Flag lo registra el inspector: no derivarlo de Business Severity.
    if result["Level_Flag"] not in ("", 1, 2, 3, "1", "2", "3"):
        raise ValueError("Level Flag: elegir 1, 2 o 3, o dejarlo pendiente.")
    return result


def build_sample(payload, lot_id, boundary_policy="higher"):
    if not isinstance(payload, dict):
        raise ValueError("Cada muestra debe ser un objeto de captura QC.")
    sample_id = identifier(payload.get("sample_id"), "sample_id")
    pallet_id = identifier(payload.get("pallet_id"), "N° PALLET")
    records = payload.get("vision_records")
    if not isinstance(records, list):
        raise ValueError(f"{sample_id}: cargar los JSON de Vision de esta muestra.")
    sample = aggregate_vision_sample(records, sample_id, lot_id, pallet_id)
    summary = sample["vision_summary"]
    if not summary["total_fruits"]:
        raise ValueError(f"{sample_id}: no se puede evaluar una muestra sin frutos.")
    if summary.get("pending_review_count", 0):
        raise ValueError(f"{sample_id}: revisar los positivos pendientes de Vision antes de evaluar.")
    if payload.get("vision_covers_sample") is not True:
        raise ValueError(
            f"{sample_id}: confirmar que las fotografías cubren los frutos de Sample, "
            "sin repetir los mismos frutos entre fotos. Si Vision cubre solo una parte, "
            "completar las fotografías; este MVP no mezcla denominadores."
        )
    fields = payload.get("qc_fields")
    if not isinstance(fields, dict):
        raise ValueError(f"{sample_id}: faltan los datos QC.")
    qc = {column["key"]: deepcopy(fields.get(column["key"], "")) for column in QC_COLUMNS}
    if fields.get("pallet_id") not in (None, "", pallet_id):
        raise ValueError(f"{sample_id}: N° PALLET no coincide con el pallet asociado.")
    qc["pallet_id"] = pallet_id
    n = fields.get("sample_count")
    if n in (None, ""):
        n = summary["total_fruits"]
    n = _count(n, "Sample")
    if n != summary["total_fruits"]:
        raise ValueError(
            f"{sample_id}: Sample debe coincidir con los frutos únicos evaluados por Vision."
        )
    qc["sample_count"] = n
    if fields.get("oleocellosis") not in (None, "", summary["oleocellosis_count"]):
        raise ValueError(
            f"{sample_id}: Oleocellosis procede de Vision y no admite sustitución manual."
        )
    qc["oleocellosis"] = summary["oleocellosis_count"]
    for column in MANUAL_DEFECTS:
        key, label = column["key"], column["label"]
        value = _count(fields.get(key), f"{sample_id}: {label}")
        if value > n:
            raise ValueError(f"{sample_id}: {label} supera Sample ({n}).")
        qc[key] = value
    for column in QC_COLUMNS[:12]:
        key = column["key"]
        if key in ("sample_count", "pallet_id"):
            continue
        value = qc[key]
        if value is None:
            qc[key] = ""
        elif isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError(f"{sample_id}: valor inválido para {column['label']}.")
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{sample_id}: valor no finito para {column['label']}.")
    sample["qc_fields"] = qc
    sample["defects"] = {
        key: {
            "business_name": meta["business_name"],
            "group": meta["group"],
            "source": "vision_ai" if key == "oleocellosis_pct" else "qc_manual",
            "pct": 100.0 * qc[key.removesuffix("_pct")] / n,
        }
        for key, meta in BUSINESS_DEFECT_MAP.items()
    }
    sample["rule_coverage"] = deepcopy(RULE_COVERAGE)
    observations = payload.get("observations", "")
    if not isinstance(observations, str):
        raise ValueError(f"{sample_id}: observaciones deben ser texto.")
    sample["observations"] = observations
    if "review_choice" in payload:
        choice = payload["review_choice"]
        if choice not in ("", "STANDARD", "EXPAND", "EXTEND", "COMPLETE"):
            raise ValueError(f"{sample_id}: elegir una decisión de revisión válida.")
        sample["review_choice"] = "EXTEND" if choice == "EXPAND" else choice
    if "image_bindings" in payload:
        sample["image_bindings"] = validate_image_bindings(
            payload["image_bindings"], records, sample_id, pallet_id, lot_id
        )
    if "reception" in payload:
        selection = payload["reception"]
        if not isinstance(selection, dict):
            raise ValueError(f"{sample_id}: la recepción debe contener el registro de la paleta.")
        selected_rows = selection.get("records")
        resolved = resolve_reception(selected_rows, selection.get("scan_input"), lot_id)
        if resolved["pallet_id"] != pallet_id or resolved["records"] != selected_rows:
            raise ValueError(f"{sample_id}: la recepción no corresponde a esta paleta y lote.")
        sample["reception"] = {
            "scan_input": resolved["scan_input"],
            "records": deepcopy(resolved["records"]),
        }
    if "review_history" in payload:
        from .additional_review import validate_review_history

        sample["review_history"] = validate_review_history(payload, qc, lot_id, boundary_policy)
        initial = sample["review_history"]["initial"]
        if "box_inspection" in initial:
            sample["box_inspection"] = deepcopy(initial["box_inspection"])
        boxes = [
            deepcopy(entry["box_inspection"])
            for entry in [initial, *sample["review_history"]["additional"]]
            if "box_inspection" in entry
        ]
        if boxes:
            sample["box_inspections"] = boxes
    elif "box_inspection" in payload:
        box = summarize_box_inspection(
            payload["box_inspection"], summary, sample.get("reception"), require_completed=True
        )
        sample["box_inspection"] = box
        sample["box_inspections"] = [deepcopy(box)]
    if sample.get("review_choice") == "COMPLETE" and not sample.get("review_history"):
        raise ValueError("COMPLETE requiere haber completado la segunda caja.")
    return sample
