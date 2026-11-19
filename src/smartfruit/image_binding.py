"""Asocia fotografías a muestras de una inspección sin cambiar el JSON Vision."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .lot_inspection import validate_lot_reception
from .reception import resolve_reception
from .vision import aggregate_vision_sample, load_vision_json, validate_vision_source_overlap

BINDING_FIELDS = frozenset({"image_id", "sample_id", "pallet_id", "lot_id"})


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: completar un identificador de texto no vacío")
    return value.strip()


def _records(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{name}: se esperaba una lista de objetos JSON de Vision")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(
                f"{name}: cada registro debe ser un objeto JSON, no una ruta o archivo"
            )
        result.append(load_vision_json(item))
    return result


def _unique_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    unique = {}
    for record in records:
        image_id = record["image_id"]
        if image_id in unique and record != unique[image_id]:
            raise ValueError(f"{image_id}: mismo image_id con contenido distinto")
        unique[image_id] = record
    return unique


def validate_image_bindings(
    bindings: Any,
    vision_records: Any,
    sample_id: str,
    pallet_id: str,
    lot_id: str,
) -> list[dict[str, str]]:
    """Valida un binding externo por fotografía única y devuelve una copia.

    Los registros Vision pueden contener duplicados idénticos para trazabilidad;
    la asociación existe una sola vez por ``image_id``. No se aceptan asociaciones
    faltantes, repetidas, ajenas al conjunto de fotos ni a otro contexto QC.
    """
    context = {
        "sample_id": _identifier(sample_id, "sample_id"),
        "pallet_id": _identifier(pallet_id, "pallet_id"),
        "lot_id": _identifier(lot_id, "lot_id"),
    }
    records = _records(vision_records, "vision_records")
    unique = _unique_records(records)
    if not isinstance(bindings, list):
        raise ValueError("image_bindings debe ser una lista de asociaciones")
    seen: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != BINDING_FIELDS:
            raise ValueError(
                "Cada image_binding debe contener exactamente image_id, sample_id, pallet_id y lot_id"
            )
        for key, value in binding.items():
            _identifier(value, f"image_bindings.{key}")
        image_id = binding["image_id"]
        if image_id not in unique:
            raise ValueError(f"image_bindings: {image_id} no pertenece a los JSON de la muestra")
        if image_id in seen:
            raise ValueError(f"image_bindings: asociación duplicada para {image_id}")
        seen.add(image_id)
        for key, expected in context.items():
            if binding[key] != expected:
                raise ValueError(
                    f"image_bindings: {image_id} no coincide con {key} de la inspección"
                )
    missing = unique.keys() - seen
    if missing:
        raise ValueError(f"image_bindings: faltan asociaciones para {sorted(missing)}")
    return deepcopy(bindings)


def _validate_reception(
    sample: dict[str, Any], sample_id: str, pallet_id: str, lot_id: str
) -> None:
    if "reception" not in sample:
        return
    selection = sample["reception"]
    if not isinstance(selection, dict):
        raise ValueError(f"{sample_id}: la recepción debe ser un objeto")
    rows = selection.get("records")
    resolved = resolve_reception(rows, selection.get("scan_input"), lot_id)
    if resolved["pallet_id"] != pallet_id or resolved["records"] != rows:
        raise ValueError(
            f"{sample_id}: la recepción no corresponde a la paleta y lote de la muestra"
        )
    for key, expected in (("lot_id", lot_id), ("pallet_id", pallet_id)):
        if key in selection and selection[key] != expected:
            raise ValueError(f"{sample_id}: {key} de recepción no coincide con la muestra")


def validate_vision_import(payload: Any, *, additional_review: bool = False) -> dict[str, Any]:
    """Valida y prepara una importación completa antes de alterar una muestra.

    ``payload`` contiene cabecera QC, todas las muestras actuales, el ``sample_id``
    de destino y los ``vision_records`` entrantes. La unicidad de fotografías se
    limita a esta inspección; no se crea un registro global ni se ejecuta Vision.
    Las listas originales nunca se modifican, incluso si falla el último archivo.
    """
    if not isinstance(payload, dict):
        raise ValueError("La importación Vision debe ser un objeto")
    header = payload.get("qc_header")
    if not isinstance(header, dict):
        raise ValueError("Falta la cabecera QC para asociar el lote")
    lot_id = _identifier(header.get("lot_id"), "AgroPeru Lot Number")
    target_id = _identifier(payload.get("sample_id"), "sample_id de destino")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("La importación requiere al menos una muestra de destino")
    if "lot_reception" in payload:
        validate_lot_reception(payload["lot_reception"], samples, lot_id)

    incoming = _records(payload.get("vision_records"), "vision_records entrantes")
    sample_ids: set[str] = set()
    ownership: dict[str, tuple[str, dict[str, Any]]] = {}
    target: tuple[str, list[dict[str, Any]]] | None = None
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("Cada muestra de la inspección debe ser un objeto")
        sample_id = _identifier(sample.get("sample_id"), "sample_id")
        pallet_id = _identifier(sample.get("pallet_id"), f"{sample_id}: pallet_id")
        if sample_id in sample_ids:
            raise ValueError(f"sample_id repetido: {sample_id}")
        sample_ids.add(sample_id)
        if "lot_id" in sample and sample["lot_id"] != lot_id:
            raise ValueError(f"{sample_id}: lot_id no coincide con la cabecera QC")
        qc_fields = sample.get("qc_fields")
        if isinstance(qc_fields, dict) and qc_fields.get("pallet_id") not in (None, "", pallet_id):
            raise ValueError(f"{sample_id}: N° PALLET no coincide con la muestra")
        records = _records(sample.get("vision_records", []), f"{sample_id}: vision_records")
        if "image_bindings" in sample:
            validate_image_bindings(sample["image_bindings"], records, sample_id, pallet_id, lot_id)
        _validate_reception(sample, sample_id, pallet_id, lot_id)
        for image_id, record in _unique_records(records).items():
            if image_id in ownership:
                raise ValueError(
                    f"{image_id}: la fotografía ya está asignada a otra muestra de la inspección"
                )
            ownership[image_id] = (sample_id, record)
        if sample_id == target_id:
            history = sample.get("review_history")
            if additional_review and history is not None and not isinstance(history, dict):
                raise ValueError("El historial de revisión debe ser un objeto.")
            if additional_review and history and history.get("additional"):
                raise ValueError("La inspección permite como máximo 2 cajas por paleta; ya está completa.")
            if incoming and "review_history" in sample and not additional_review:
                raise ValueError(
                    "Esta paleta ya tiene revisiones adicionales; añade la caja desde EXTEND "
                    "para conservar el historial."
                )
            target = (pallet_id, records)

    if target is None:
        raise ValueError(f"La muestra de destino '{target_id}' no existe en la inspección")
    pallet_id, current = target
    for record in incoming:
        image_id = record["image_id"]
        if image_id in ownership:
            owner_id, previous = ownership[image_id]
            if owner_id != target_id:
                raise ValueError(
                    f"{image_id}: la fotografía ya está asignada a otra muestra de la inspección"
                )
            if previous != record:
                raise ValueError(f"{image_id}: mismo image_id con contenido distinto")
        else:
            ownership[image_id] = (target_id, record)

    validate_vision_source_overlap(record for _, record in ownership.values())

    # Conservar duplicados idénticos en los registros para que el agregador pueda
    # informar duplicate_image_ids_ignored sin aumentar las cantidades.
    merged = current + incoming
    summary = None
    bindings = []
    if merged:
        summary = aggregate_vision_sample(merged, target_id, lot_id, pallet_id)["vision_summary"]
        bindings = [
            {
                "image_id": image_id,
                "sample_id": target_id,
                "pallet_id": pallet_id,
                "lot_id": lot_id,
            }
            for image_id in summary["image_ids"]
        ]
    return {"vision_records": merged, "inspection_summary": summary, "image_bindings": bindings}
