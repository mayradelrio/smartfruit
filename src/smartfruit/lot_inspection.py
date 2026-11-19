"""Integridad de la inspección de todas las paletas del lote seleccionado."""

from copy import deepcopy
from datetime import datetime

from .reception import resolve_reception_lot

PALLET_STATUSES = ("PENDING", "SELECTED", "IN_PROGRESS", "COMPLETED", "SKIPPED")


def pallet_inspection_state(value, pallet_id=None):
    """Validate explicit operational status without inferring fruit measurements."""
    if not isinstance(value, dict):
        raise ValueError("El estado de una paleta debe ser un objeto.")
    pallet_id = pallet_id or value.get("pallet_id")
    if not isinstance(pallet_id, str) or not pallet_id.strip():
        raise ValueError("El estado requiere identificar la paleta.")
    status = value.get("inspection_status", "PENDING")
    if status not in PALLET_STATUSES:
        raise ValueError("Estado de inspección de paleta no reconocido.")
    reason = value.get("skip_reason", "")
    if not isinstance(reason, str):
        raise ValueError("El motivo de omisión debe ser texto.")
    result = {"pallet_id": pallet_id.strip(), "inspection_status": status, "skip_reason": reason.strip()}
    for name in ("selected_at", "completed_at"):
        timestamp = value.get(name)
        if timestamp not in (None, ""):
            if not isinstance(timestamp, str):
                raise ValueError(f"{name}: usar una fecha y hora ISO válida.")
            try:
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"{name}: usar una fecha y hora ISO válida.") from exc
        result[name] = timestamp or None
    if status != "SKIPPED" and reason.strip():
        raise ValueError("El motivo de omisión corresponde solo a una paleta SKIPPED.")
    return result


def validate_uninspected_sample(sample):
    """A skipped/unselected row is context, never a zero-defect measurement."""
    from .inspection import DEFECT_COLUMNS

    state = pallet_inspection_state(sample)
    if state["inspection_status"] == "COMPLETED":
        return state
    fields = sample.get("qc_fields", {})
    if state["inspection_status"] in ("PENDING", "SELECTED", "SKIPPED") and (
        sample.get("vision_records") or sample.get("review_history")
        or sample.get("box_inspection") or sample.get("box_inspections")
        or isinstance(fields, dict) and any(
            fields.get(key) not in (None, "", 0)
            for key in ("sample_count", *(column["key"] for column in DEFECT_COLUMNS))
        )
    ):
        raise ValueError("Una paleta sin inspección no puede contener mediciones ni evidencia de una caja.")
    return state


def validate_lot_reception(selection, samples, lot_id):
    """Comprueba el padrón recibido, sin convertirlo en mediciones QC.

    Es una extensión opcional: capturas anteriores sin padrón siguen siendo
    compatibles. En el nuevo flujo, cada paleta recibida debe tener una sola fila.
    """
    if not isinstance(selection, dict):
        raise ValueError("La recepción del lote debe contener su selección y registros.")
    rows = selection.get("records")
    scan_input = selection.get("scan_input")
    selected_lot = selection.get("lot_id", lot_id)
    if scan_input in (None, "") and "lot_id" not in selection:
        raise ValueError("La recepción del lote debe identificar el lote seleccionado.")
    resolved = resolve_reception_lot(rows, scan_input, selected_lot)
    if resolved["lot_id"] != lot_id or resolved["records"] != rows:
        raise ValueError("La recepción incluye registros ajenos al lote de la inspección.")
    expected = {pallet["pallet_id"]: pallet for pallet in resolved["pallets"]}
    if not isinstance(samples, list):
        raise ValueError("La inspección del lote debe contener sus filas por paleta.")
    explicit_states = "pallets" in selection or any(
        isinstance(sample, dict) and "inspection_status" in sample for sample in samples
    )
    states = {}
    if "pallets" in selection:
        if not isinstance(selection["pallets"], list):
            raise ValueError("El estado de las paletas del lote debe ser una lista.")
        for entry in selection["pallets"]:
            state = pallet_inspection_state(entry)
            key = state["pallet_id"]
            if key not in expected or key in states:
                raise ValueError("El padrón de estados contiene una paleta ajena o repetida.")
            states[key] = state
    seen = set()
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("Cada fila del lote debe corresponder a una paleta.")
        pallet_id = sample.get("pallet_id")
        if not isinstance(pallet_id, str) or not pallet_id.strip():
            raise ValueError("Completar N° PALLET en cada fila del lote.")
        pallet_id = pallet_id.strip()
        if pallet_id in seen:
            raise ValueError(f"El lote requiere una sola fila por paleta: {pallet_id} repetida.")
        seen.add(pallet_id)
        if pallet_id not in expected:
            raise ValueError(f"La paleta {pallet_id} no pertenece al lote recibido.")
        if explicit_states:
            status = sample.get("inspection_status", states.get(pallet_id, {}).get("inspection_status", "COMPLETED"))
            state = pallet_inspection_state({**sample, "inspection_status": status}, pallet_id)
            if pallet_id in states and "inspection_status" in sample and state != states[pallet_id]:
                raise ValueError("El estado de la paleta no coincide con su fila de inspección.")
            states[pallet_id] = state if "inspection_status" in sample or pallet_id not in states else states[pallet_id]
            validate_uninspected_sample({**sample, "inspection_status": status})
        receipt = sample.get("reception")
        if (
            not isinstance(receipt, dict)
            or receipt.get("records") != expected[pallet_id]["records"]
        ):
            raise ValueError(
                f"La recepción de la paleta {pallet_id} no coincide con el lote recibido."
            )
    missing = expected.keys() - (seen | states.keys())
    if missing:
        raise ValueError(f"Faltan filas QC para las paletas del lote: {sorted(missing)}.")
    if resolved["selection_mode"] == "lot":
        result = {"lot_id": resolved["lot_id"], "records": deepcopy(rows)}
    else:
        result = {"scan_input": resolved["scan_input"], "records": deepcopy(rows)}
    if "lot_id" in selection:
        result["lot_id"] = resolved["lot_id"]
    if explicit_states:
        for key, state in states.items():
            if state["inspection_status"] == "COMPLETED" and key not in seen:
                raise ValueError("Una paleta COMPLETED requiere su muestra inspeccionada.")
        result["pallets"] = [states[key] for key in expected]
    return result
