"""Adjudicación humana de detecciones binarias, sin cambiar la predicción original."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

REVIEW_STATUSES = frozenset({"pending", "confirmed", "rejected"})
OVERRIDE_LABELS = frozenset({"styler", "scar", "inking", "clean", "other"})
_AUDIT_FIELDS = ("reviewed_by", "reviewed_at", "override_reason", "override_label")


def review_status(prediction: Mapping[str, Any]) -> str:
    """Un positivo histórico sin adjudicación sigue pendiente de revisión."""
    return prediction.get("review_status", "pending")


def validate_prediction_review(prediction: Mapping[str, Any], reference: str) -> None:
    status = review_status(prediction)
    if not isinstance(status, str) or status not in REVIEW_STATUSES:
        raise ValueError(f"{reference}: review_status debe ser pending, confirmed o rejected.")
    for field in _AUDIT_FIELDS:
        value = prediction.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{reference}: {field} debe ser texto o null.")
    if status == "pending":
        if any(prediction.get(field) not in (None, "") for field in _AUDIT_FIELDS):
            raise ValueError(f"{reference}: una revisión pendiente no admite adjudicación previa.")
        return
    if prediction.get("predicted_class") != "con_oleocelosis":
        raise ValueError(f"{reference}: este flujo de revisión corresponde a positivos de Vision.")
    if not (prediction.get("reviewed_by") or "").strip():
        raise ValueError(f"{reference}: registrar quién revisó la detección.")
    timestamp = prediction.get("reviewed_at")
    try:
        reviewed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{reference}: reviewed_at debe ser una fecha ISO con zona horaria.") from exc
    if reviewed_at.tzinfo is None:
        raise ValueError(f"{reference}: reviewed_at debe incluir zona horaria.")
    label = prediction.get("override_label")
    if status == "confirmed" and label not in (None, ""):
        raise ValueError(f"{reference}: una detección confirmada no admite override_label.")
    if status == "rejected":
        if label not in OVERRIDE_LABELS:
            raise ValueError(f"{reference}: seleccionar el motivo del positivo rechazado.")
        if label == "other" and not (prediction.get("override_reason") or "").strip():
            raise ValueError(f"{reference}: describir el motivo de la corrección 'other'.")


def initialize_vision_review(record: Mapping[str, Any]) -> dict[str, Any]:
    """Añade campos opcionales de revisión a una copia; conserva contrato y evidencia."""
    from .vision import load_vision_json

    result = load_vision_json(record)
    for prediction in result["fruit_predictions"]:
        if prediction["predicted_class"] != "con_oleocelosis":
            continue
        prediction.setdefault("review_status", "pending")
        for field in _AUDIT_FIELDS:
            prediction.setdefault(field, None)
    return result


def review_vision_prediction(
    record: Mapping[str, Any],
    crop_id: str,
    status: str,
    reviewed_by: str,
    *,
    override_label: str | None = None,
    override_reason: str | None = None,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Adjudica un positivo sin tocar clases, probabilidades ni conteos crudos.

    El override es una observación QC. Nunca añade cantidades a otros defectos.
    """
    if status not in ("confirmed", "rejected"):
        raise ValueError("Elegir confirmed o rejected para adjudicar una detección.")
    result = initialize_vision_review(record)
    prediction = next((p for p in result["fruit_predictions"] if p["crop_id"] == crop_id), None)
    if prediction is None:
        raise ValueError(f"No se encontró la detección {crop_id}.")
    prediction.update({
        "review_status": status,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at or datetime.now(timezone.utc).isoformat(),
        "override_label": override_label,
        "override_reason": override_reason,
    })
    validate_prediction_review(prediction, f"{result['image_id']}/{crop_id}")
    return deepcopy(result)
