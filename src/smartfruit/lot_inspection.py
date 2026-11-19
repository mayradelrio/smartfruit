"""Integridad de la inspección de todas las paletas del lote seleccionado."""

from copy import deepcopy

from .reception import resolve_reception_lot


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
    seen = set()
    if not isinstance(samples, list):
        raise ValueError("La inspección del lote debe contener sus filas por paleta.")
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
        receipt = sample.get("reception")
        if (
            not isinstance(receipt, dict)
            or receipt.get("records") != expected[pallet_id]["records"]
        ):
            raise ValueError(
                f"La recepción de la paleta {pallet_id} no coincide con el lote recibido."
            )
    missing = expected.keys() - seen
    if missing:
        raise ValueError(f"Faltan filas QC para las paletas del lote: {sorted(missing)}.")
    if resolved["selection_mode"] == "lot":
        return {"lot_id": resolved["lot_id"], "records": deepcopy(rows)}
    result = {"scan_input": resolved["scan_input"], "records": deepcopy(rows)}
    if "lot_id" in selection:
        result["lot_id"] = resolved["lot_id"]
    return result
