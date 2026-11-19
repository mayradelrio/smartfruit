"""Additional boxes extend one pallet's observed sample without losing its history."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .box_inspection import summarize_box_inspection
from .business_rules import evaluate_business_severity
from .vision import aggregate_vision_sample, load_vision_json


def _manual_keys() -> tuple[str, ...]:
    from .inspection import MANUAL_DEFECTS

    return tuple(column["key"] for column in MANUAL_DEFECTS)


def _records(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label}: cargar al menos un JSON nuevo de Vision.")
    if any(not isinstance(record, dict) for record in value):
        raise ValueError(f"{label}: cada archivo debe contener un objeto JSON de Vision.")
    return [load_vision_json(record) for record in value]


def _count(value: Any, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{label}: registrar una cantidad entera entre 0 y {maximum}.")
    return value


def _additional_fields(
    entry: dict[str, Any], sample_id: str, pallet_id: str, lot_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, int], dict[str, int]]:
    records = _records(entry.get("vision_records"), "Revisión adicional")
    ids = [record["image_id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("La revisión adicional contiene fotografías repetidas; elige otros JSON.")
    summary = aggregate_vision_sample(records, sample_id, lot_id, pallet_id)["vision_summary"]
    total = summary["total_fruits"]
    if not total:
        raise ValueError("La caja adicional debe contener frutos evaluados por Vision.")
    supplied = entry.get("manual_defects")
    expected = set(_manual_keys())
    if not isinstance(supplied, dict) or set(supplied) != expected:
        raise ValueError(
            "Registrar todos los defectos manuales de la caja adicional; "
            "un campo pendiente no equivale a cero."
        )
    manual = {key: _count(supplied[key], f"Revisión adicional: {key}", total) for key in _manual_keys()}
    fields = {
        "sample_count": total,
        "oleocellosis": summary["oleocellosis_count"],
        **manual,
    }
    return records, summary, manual, fields


def _sample_model(
    original: dict[str, Any], records: list[dict[str, Any]], fields: dict[str, Any],
    lot_id: str, boundary_policy: str,
) -> dict[str, Any]:
    from .inspection import build_sample

    sample = deepcopy(original)
    sample.pop("review_history", None)
    sample.pop("image_bindings", None)
    sample.pop("box_inspection", None)
    sample.pop("box_inspections", None)
    sample.pop("review_choice", None)
    sample["vision_records"] = deepcopy(records)
    sample["qc_fields"] = deepcopy(fields)
    sample["vision_covers_sample"] = True
    return evaluate_business_severity(build_sample(sample, lot_id, boundary_policy), boundary_policy)


def validate_review_history(
    sample: dict[str, Any], qc_fields: dict[str, Any], lot_id: str,
    boundary_policy: str = "higher",
) -> dict[str, Any]:
    """Rebuild each review and require its sum to match the current pallet.

    History is not an independent set of totals supplied by a client. The original
    JSONs and explicitly observed manual counts determine each round, the final
    counts, and the weighted percentages. General QC metadata can still be revised
    by the inspector without rewriting the original measurement snapshots.
    """
    history = sample.get("review_history")
    if not isinstance(history, dict) or not isinstance(history.get("initial"), dict):
        raise ValueError("El historial de revisión debe conservar la inspección inicial.")
    additions = history.get("additional")
    if not isinstance(additions, list) or not additions:
        raise ValueError("El historial debe contener al menos una revisión adicional.")
    if len(additions) > 1:
        raise ValueError("La inspección permite como máximo 2 cajas por paleta.")
    initial = history["initial"]
    records = _records(initial.get("vision_records"), "Inspección inicial")
    initial_fields = initial.get("qc_fields")
    if not isinstance(initial_fields, dict):
        raise ValueError("El historial debe conservar los campos QC de la inspección inicial.")
    model = _sample_model(sample, records, initial_fields, lot_id, boundary_policy)
    initial_fields = model["qc_fields"]
    initial_summary = model["vision_summary"]
    recommendation = model["business_severity"]["recommendation"]
    canonical = {
        "initial": {
            "vision_records": deepcopy(records),
            "qc_fields": deepcopy(initial_fields),
            "inspection_summary": deepcopy(initial_summary),
            "system_recommendation": recommendation,
        },
        "additional": [],
    }
    initial_metadata = initial.get("box_inspection", sample.get("box_inspection"))
    box_ids = set()
    if initial_metadata is not None:
        initial_box = summarize_box_inspection(
            initial_metadata, initial_summary, sample.get("reception"), require_completed=True
        )
        if "box_inspection" in sample:
            current_box = summarize_box_inspection(
                sample["box_inspection"], initial_summary, sample.get("reception"),
                require_completed=True,
            )
            if current_box != initial_box:
                raise ValueError("Los datos de la caja inicial no coinciden con su historial.")
        canonical["initial"]["box_inspection"] = initial_box
        box_ids.add(initial_box["sample_box_id"])
    seen = {record["image_id"] for record in records}
    accumulated = deepcopy(initial_fields)
    count_keys = ("sample_count", "oleocellosis", *_manual_keys())
    for index, supplied in enumerate(additions, start=2):
        if not isinstance(supplied, dict):
            raise ValueError("Cada revisión adicional del historial debe ser un objeto.")
        number = supplied.get("review_number")
        if not isinstance(number, int) or isinstance(number, bool) or number != index:
            raise ValueError("El número de cada revisión adicional debe conservar su secuencia.")
        if supplied.get("trigger_decision") not in ("EXPAND", "EXTEND"):
            raise ValueError("Una revisión adicional requiere la decisión EXTEND del inspector.")
        observations = supplied.get("observations", "")
        if not isinstance(observations, str):
            raise ValueError("Las observaciones de la revisión adicional deben ser texto.")
        incoming, summary, manual, fields = _additional_fields(
            supplied, sample["sample_id"], sample["pallet_id"], lot_id
        )
        additional_box = None
        if "box_inspection" in supplied:
            additional_box = summarize_box_inspection(
                supplied["box_inspection"], summary, sample.get("reception"),
                require_completed=True,
            )
            if additional_box["sample_box_id"] in box_ids:
                raise ValueError("Cada caja de la paleta debe tener un sample_box_id distinto.")
            box_ids.add(additional_box["sample_box_id"])
        elif initial_metadata is not None:
            raise ValueError("La caja adicional requiere su identificación y cierre explícitos.")
        overlaps = seen.intersection(record["image_id"] for record in incoming)
        if overlaps:
            raise ValueError(
                f"Las fotografías {sorted(overlaps)} ya se usaron en una revisión anterior."
            )
        seen.update(record["image_id"] for record in incoming)
        records.extend(incoming)
        for key in count_keys:
            accumulated[key] += fields[key]
        before = recommendation
        model = _sample_model(sample, records, accumulated, lot_id, boundary_policy)
        recommendation = model["business_severity"]["recommendation"]
        canonical["additional"].append({
            "review_number": index,
            "trigger_decision": "EXTEND",
            "vision_records": deepcopy(incoming),
            "manual_defects": manual,
            "qc_fields": fields,
            "inspection_summary": deepcopy(summary),
            "observations": observations,
            "system_recommendation_before": before,
            "system_recommendation_after": "COMPLETE",
        })
        if additional_box is not None:
            canonical["additional"][-1]["box_inspection"] = additional_box
    if records != sample.get("vision_records"):
        raise ValueError("Los JSON acumulados de la paleta no coinciden con su historial de revisión.")
    if any(qc_fields[key] != accumulated[key] for key in count_keys):
        raise ValueError("Las cantidades acumuladas de la paleta no coinciden con su historial de revisión.")
    return canonical


def add_additional_review(
    payload: Any, use_predictive: bool = False, provider: Any = None,
    boundary_policy: str = "higher",
) -> dict[str, Any]:
    """Validate the whole proposed round, then return an updated capture and report.

    The caller commits the returned capture only after this function succeeds.
    Failed JSON imports, duplicate photos, missing manual observations, and invalid
    histories never mutate the input or partially increase a pallet's quantities.
    """
    from .image_binding import validate_vision_import
    from .workflow import evaluate_inspection

    if not isinstance(payload, dict):
        raise ValueError("La revisión adicional debe ser un objeto de captura.")
    if payload.get("inspector_decision") not in ("EXPAND", "EXTEND"):
        raise ValueError("Selecciona EXTEND para registrar una caja adicional de esta paleta.")
    target_id = payload.get("sample_id")
    if not isinstance(target_id, str) or not target_id.strip():
        raise ValueError("Seleccionar la paleta de destino de la revisión adicional.")
    target_id = target_id.strip()
    supplied = payload.get("additional_review")
    if not isinstance(supplied, dict):
        raise ValueError("Completar los JSON y defectos de la caja adicional.")
    observations = supplied.get("observations", "")
    if not isinstance(observations, str):
        raise ValueError("Las observaciones de la revisión adicional deben ser texto.")
    capture = deepcopy(payload)
    for key in (
        "sample_id", "inspector_decision", "additional_review", "confirmed", "final_decisions",
        "inspector_confirmed", "confirmed_at", "inspector_final_decision",
    ):
        capture.pop(key, None)
    current_report = evaluate_inspection(capture, use_predictive, provider, boundary_policy)
    current = next((sample for sample in current_report["samples"] if sample["sample_id"] == target_id), None)
    if current is None:
        raise ValueError(f"La muestra '{target_id}' no existe en esta inspección.")
    if current.get("review_history", {}).get("additional"):
        raise ValueError("La inspección permite como máximo 2 cajas por paleta; ya está completa.")
    target = next(sample for sample in capture["samples"] if sample["sample_id"].strip() == target_id)
    incoming, summary, manual, fields = _additional_fields(
        supplied, target_id, current["pallet_id"], current_report["lot_id"]
    )
    prior_ids = {
        record["image_id"]
        for sample in capture["samples"] for record in sample["vision_records"]
    }
    repeated = prior_ids.intersection(record["image_id"] for record in incoming)
    if repeated:
        raise ValueError(
            f"Las fotografías {sorted(repeated)} ya se utilizaron; elige otros JSON para la caja adicional."
        )
    imported = validate_vision_import(
        {**capture, "sample_id": target_id, "vision_records": incoming}, additional_review=True
    )
    history = deepcopy(current.get("review_history"))
    if history is None:
        history = {
            "initial": {
                "vision_records": deepcopy(target["vision_records"]),
                "qc_fields": deepcopy(current["qc_fields"]),
                "inspection_summary": deepcopy(current["inspection_summary"]),
                "system_recommendation": current["final_recommendation"],
            },
            "additional": [],
        }
        if "box_inspection" in current:
            history["initial"]["box_inspection"] = deepcopy(current["box_inspection"])
    history["additional"].append({
        "review_number": len(history["additional"]) + 2,
        "trigger_decision": "EXTEND",
        "vision_records": incoming,
        "manual_defects": manual,
        "qc_fields": fields,
        "inspection_summary": summary,
        "observations": observations,
        "system_recommendation_before": current["final_recommendation"],
    })
    if "box_inspection" in supplied:
        history["additional"][-1]["box_inspection"] = summarize_box_inspection(
            supplied["box_inspection"], summary, current.get("reception"), require_completed=True
        )
    elif "box_inspection" in current:
        raise ValueError("La caja adicional requiere su identificación y cierre explícitos.")
    target["vision_records"] = imported["vision_records"]
    target["image_bindings"] = imported["image_bindings"]
    target["vision_covers_sample"] = True
    target["qc_fields"] = deepcopy(current["qc_fields"])
    for key in ("sample_count", "oleocellosis", *_manual_keys()):
        target["qc_fields"][key] += fields[key]
    target["review_history"] = history
    target["review_choice"] = "COMPLETE"
    for sample in capture["samples"]:
        for key in ("inspector_confirmed", "inspector_final_decision", "confirmed_at", "confirmed"):
            sample.pop(key, None)
    report = evaluate_inspection(capture, use_predictive, provider, boundary_policy)
    updated = next(sample for sample in report["samples"] if sample["sample_id"] == target_id)
    target["review_history"] = deepcopy(updated["review_history"])
    # Return the canonical header too: Reason may have been regenerated from the totals.
    capture["qc_header"] = deepcopy(report["qc_header"])
    return {
        "capture": capture,
        "report": report,
        "review": deepcopy(updated["review_history"]["additional"][-1]),
    }
