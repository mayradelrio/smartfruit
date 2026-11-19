"""Set adjudicado y métricas binarias; la confianza del modelo no es exactitud."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .vision import load_vision_json
from .vision_review import OVERRIDE_LABELS, review_status

QC_FINAL_LABELS = OVERRIDE_LABELS | {"oleocellosis", "not_oleocellosis"}


def build_adjudicated_dataset(
    records: Iterable[Any], adjudications: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Conserva pendientes y acepta adjudicaciones explícitas de negativos.

    Revisar únicamente positivos no produce evidencia de falsos negativos.
    Las correcciones externas se vinculan por (image_id, crop_id), nunca por
    probabilidad ni por un conteo agregado. No modifican la inspección original.
    """
    supplied: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in adjudications:
        if not isinstance(item, Mapping):
            raise ValueError("Cada adjudicación QC debe ser un objeto.")
        key = (item.get("image_id"), item.get("crop_id"))
        if any(not isinstance(part, str) or not part.strip() for part in key):
            raise ValueError("La adjudicación requiere image_id y crop_id.")
        if key in supplied:
            raise ValueError("Detección adjudicada más de una vez.")
        if not isinstance(item.get("qc_final_label"), str) or item["qc_final_label"] not in QC_FINAL_LABELS:
            raise ValueError("qc_final_label no reconocido.")
        for field in ("notes", "reviewed_by", "reviewed_at"):
            if item.get(field) is not None and not isinstance(item[field], str):
                raise ValueError(f"{field} debe ser texto o null.")
        supplied[key] = item
    rows = []
    seen = {}
    for source in records:
        record = load_vision_json(source)
        image_id = record["image_id"]
        if image_id in seen:
            if record != seen[image_id]:
                raise ValueError(f"{image_id}: mismo image_id con contenido distinto")
            continue
        seen[image_id] = record
        for prediction in record["fruit_predictions"]:
            key = (image_id, prediction["crop_id"])
            qc_label = None
            notes = prediction.get("override_reason") or ""
            reviewer = prediction.get("reviewed_by")
            reviewed_at = prediction.get("reviewed_at")
            if review_status(prediction) == "confirmed":
                qc_label = "oleocellosis"
            elif review_status(prediction) == "rejected":
                qc_label = prediction["override_label"]
            if key in supplied:
                adjudication = supplied.pop(key)
                qc_label = adjudication["qc_final_label"]
                notes = adjudication.get("notes", notes)
                reviewer = adjudication.get("reviewed_by", reviewer)
                reviewed_at = adjudication.get("reviewed_at", reviewed_at)
            positive = prediction["predicted_class"] == "con_oleocelosis"
            error = None
            if qc_label is not None:
                final_positive = qc_label == "oleocellosis"
                if positive and not final_positive:
                    error = f"oleocellosis -> {qc_label}"
                elif not positive and final_positive:
                    error = "false negative oleocellosis"
                else:
                    error = "correct"
            rows.append({
                "image_id": image_id,
                "crop_id": prediction["crop_id"],
                "model_prediction": prediction["predicted_class"],
                "model_probability": prediction["oleocellosis_probability"],
                "qc_final_label": qc_label,
                "error_type": error,
                "notes": notes,
                "reviewed_by": reviewer,
                "reviewed_at": reviewed_at,
            })
    if supplied:
        raise ValueError("La adjudicación hace referencia a una detección inexistente.")
    return rows


def calculate_vision_metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Métricas sobre detecciones adjudicadas; los pendientes no cuentan como sanos."""
    tp = fp = fn = tn = pending = 0
    unreviewed_negatives = 0
    seen = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Cada registro del set adjudicado debe ser un objeto.")
        key = (row.get("image_id"), row.get("crop_id"))
        if any(not isinstance(part, str) or not part.strip() for part in key):
            raise ValueError("El set adjudicado requiere image_id y crop_id.")
        if key in seen:
            raise ValueError("El set adjudicado contiene una detección duplicada.")
        seen.add(key)
        predicted = row.get("model_prediction")
        if predicted not in ("con_oleocelosis", "sin_oleocelosis"):
            raise ValueError("model_prediction debe conservar una clase binaria de Vision.")
        qc_label = row.get("qc_final_label")
        if qc_label is None:
            pending += 1
            unreviewed_negatives += predicted == "sin_oleocelosis"
            continue
        if not isinstance(qc_label, str) or qc_label not in QC_FINAL_LABELS:
            raise ValueError("qc_final_label no reconocido.")
        positive = predicted == "con_oleocelosis"
        actual = qc_label == "oleocellosis"
        tp += positive and actual
        fp += positive and not actual
        fn += not positive and actual
        tn += not positive and not actual
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {
        "evaluation_scope": "QC-adjudicated detections only",
        "confusion_matrix": {
            "labels": ["oleocellosis", "not_oleocellosis"],
            "rows": "qc_actual",
            "columns": "model_prediction",
            "values": [[tp, fn], [fp, tn]],
        },
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "adjudicated_count": tp + fp + fn + tn,
        "pending_count": pending,
        "unreviewed_count": pending,
        "adjudication_coverage": (tp + fp + fn + tn) / len(seen) if seen else None,
        "unreviewed_model_negatives": unreviewed_negatives,
        "recall_scope": "adjudicated subset; unreviewed detections excluded",
        "complete": bool(seen) and pending == 0,
        "evaluation_status": (
            "unreviewed" if not tp + fp + fn + tn else "partial" if pending else "adjudicated"
        ),
    }
