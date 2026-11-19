"""Consume el contrato Vision existente sin ejecutar ni modificar el modelo."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from .vision_review import review_status, validate_prediction_review

VISION_FIELDS = frozenset(
    {
        "image_id",
        "partition",
        "total_fruits",
        "oleocellosis_count",
        "oleocellosis_pct",
        "mean_confidence",
        "fruit_predictions",
    }
)
PREDICTION_FIELDS = frozenset(
    {"crop_id", "predicted_class", "oleocellosis_probability", "confidence"}
)
VISION_CLASSES = frozenset({"con_oleocelosis", "sin_oleocelosis"})
_FRUIT_CROP_SUFFIX = re.compile(r"_L\d+$", re.IGNORECASE)
_PHOTO_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"})


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: debe ser un número finito")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name}: debe estar entre {minimum:g} y {maximum:g}")
    return number


def _identifier(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: debe ser un identificador no vacío")


def load_vision_json(source: Any) -> dict[str, Any]:
    """Lee un path, bytes, archivo abierto o mapping; devuelve una copia validada.

    Las claves adicionales se conservan. Un ``str`` representa una ruta, no el
    contenido JSON; para contenido en memoria se pueden pasar bytes o un archivo.
    """
    try:
        if isinstance(source, Mapping):
            data = deepcopy(dict(source))
        elif isinstance(source, (bytes, bytearray)):
            data = json.loads(bytes(source).decode("utf-8-sig"))
        elif hasattr(source, "read"):
            content = source.read()
            if isinstance(content, bytes):
                content = content.decode("utf-8-sig")
            data = json.loads(content)
        else:
            data = json.loads(Path(source).read_text(encoding="utf-8-sig"))
    except (OSError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"No se pudo leer el JSON de Vision: {exc}") from exc
    validate_vision_record(data)
    return data


def validate_vision_record(data: Any) -> None:
    """Valida tipos, dominios y coherencia de un registro del contrato actual."""
    if not isinstance(data, dict):
        raise ValueError("El JSON de Vision debe ser un objeto")
    missing = VISION_FIELDS - data.keys()
    if missing:
        raise ValueError(f"Vision: faltan campos {sorted(missing)}")
    _identifier(data["image_id"], "image_id")
    image_id = data["image_id"]
    _identifier(data["partition"], f"{image_id}: partition")

    for name in ("total_fruits", "oleocellosis_count"):
        value = data[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{image_id}: {name} debe ser un entero no negativo")
    total = data["total_fruits"]
    count = data["oleocellosis_count"]
    if count > total:
        raise ValueError(f"{image_id}: oleocellosis_count supera total_fruits")
    percentage = _number(data["oleocellosis_pct"], f"{image_id}: oleocellosis_pct", 0, 100)
    expected_percentage = 100.0 * count / total if total else 0.0
    # Tolerancia de coherencia presente en la integración original; no es una
    # frontera de severidad ni se utiliza para decidir.
    if abs(expected_percentage - percentage) > 0.02:
        raise ValueError(f"{image_id}: oleocellosis_pct inconsistente")

    predictions = data["fruit_predictions"]
    if not isinstance(predictions, list) or len(predictions) != total:
        raise ValueError(f"{image_id}: fruit_predictions no coincide con total_fruits")
    mean_confidence = data["mean_confidence"]
    if mean_confidence is not None or total:
        _number(mean_confidence, f"{image_id}: mean_confidence", 0, 1)

    crop_ids: set[str] = set()
    affected = 0
    for prediction in predictions:
        if not isinstance(prediction, dict):
            raise ValueError(f"{image_id}: cada predicción debe ser un objeto")
        missing = PREDICTION_FIELDS - prediction.keys()
        if missing:
            raise ValueError(f"{image_id}: predicción sin campos {sorted(missing)}")
        crop_id = prediction["crop_id"]
        _identifier(crop_id, f"{image_id}: crop_id")
        if crop_id in crop_ids:
            raise ValueError(f"{image_id}: crop_id duplicado {crop_id}")
        crop_ids.add(crop_id)
        predicted_class = prediction["predicted_class"]
        if not isinstance(predicted_class, str) or predicted_class not in VISION_CLASSES:
            raise ValueError(f"{image_id}: predicted_class no reconocida")
        affected += predicted_class == "con_oleocelosis"
        _number(prediction["confidence"], f"{image_id}/{crop_id}: confidence", 0, 1)
        _number(
            prediction["oleocellosis_probability"],
            f"{image_id}/{crop_id}: oleocellosis_probability",
            0,
            1,
        )
        validate_prediction_review(prediction, f"{image_id}/{crop_id}")
    if affected != count:
        raise ValueError(f"{image_id}: las clases por fruto no coinciden con oleocellosis_count")


def _source_stem(value: str) -> str:
    filename = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
    stem, extension = filename.rsplit(".", 1) if "." in filename else (filename, "")
    return (stem if "." + extension.lower() in _PHOTO_EXTENSIONS else filename).casefold()


def validate_vision_source_overlap(records: Iterable[Any]) -> None:
    """Impide contar una foto completa junto con sus recortes individuales.

    Los JSON históricos identifican la foto por ``image_id``. La inferencia nueva
    usa un hash de contenido y conserva su nombre original en ``inference``.
    Se cruzan ambas referencias; diferentes recortes de una foto siguen siendo
    frutos distintos y se pueden sumar. No pretende reconocer frutos entre
    imágenes arbitrarias sin una referencia de procedencia compartida.
    """
    seen_images: set[str] = set()
    groups: dict[str, dict[str, Any]] = {}
    for source in records:
        record = source if isinstance(source, dict) else load_vision_json(source)
        image_id = record["image_id"]
        if image_id in seen_images:
            continue
        seen_images.add(image_id)
        metadata = record.get("inference")
        if isinstance(metadata, dict) and metadata.get("input_kind") in ("fruit_crop", "scene"):
            source_name = metadata.get("source_filename")
            if not isinstance(source_name, str) or not source_name.strip():
                source_name = image_id
            stem = _source_stem(source_name)
            is_crop = metadata["input_kind"] == "fruit_crop"
        else:
            stem = _source_stem(image_id)
            is_crop = bool(_FRUIT_CROP_SUFFIX.search(stem)) and record["total_fruits"] == 1
        group = _FRUIT_CROP_SUFFIX.sub("", stem) if is_crop else stem
        # Un recorte con nombre libre no demuestra parentesco con otra foto.
        # Aun así, dos inferencias del mismo nombre sí se consideran solapadas.
        previous = groups.setdefault(group, {"scene": None, "crops": {}})
        conflict = previous["scene"]
        if is_crop:
            conflict = conflict or previous["crops"].get(stem)
        elif previous["crops"]:
            conflict = conflict or next(iter(previous["crops"].values()))
        if conflict is not None:
            raise ValueError(
                f"{image_id} y {conflict}: las fotografías comparten frutos de {group}. "
                "Usa el JSON de la foto completa o sus recortes, sin combinarlos."
            )
        if is_crop:
            previous["crops"][stem] = image_id
        else:
            previous["scene"] = image_id


def aggregate_vision_sample(
    records_or_paths: Iterable[Any],
    sample_id: str,
    lot_id: str | None = None,
    pallet_id: str | None = None,
    low_confidence_threshold: float = 0.70,
) -> dict[str, Any]:
    """Agrega una muestra explícita sin contar dos veces una fotografía.

    Los duplicados idénticos se registran y se ignoran. Un mismo ``image_id`` con
    contenido distinto exige corregir la entrada en vez de elegir un resultado
    silenciosamente. No identifica frutos repetidos entre fotografías distintas.
    """
    _identifier(sample_id, "sample_id")
    threshold = _number(low_confidence_threshold, "low_confidence_threshold", 0, 1)
    records: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for source in records_or_paths:
        record = load_vision_json(source)
        image_id = record["image_id"]
        if image_id in records:
            if record != records[image_id]:
                raise ValueError(f"{image_id}: mismo image_id con contenido distinto")
            duplicates.append(image_id)
            continue
        records[image_id] = record
    if not records:
        raise ValueError("No hay JSON válidos para agregar.")
    validate_vision_source_overlap(records.values())

    total = sum(record["total_fruits"] for record in records.values())
    raw_affected = sum(record["oleocellosis_count"] for record in records.values())
    positives = [
        prediction
        for record in records.values()
        for prediction in record["fruit_predictions"]
        if prediction["predicted_class"] == "con_oleocelosis"
    ]
    affected = sum(review_status(prediction) == "confirmed" for prediction in positives)
    pending = sum(review_status(prediction) == "pending" for prediction in positives)
    rejected = sum(review_status(prediction) == "rejected" for prediction in positives)
    reviews = []
    for record in records.values():
        for prediction in record["fruit_predictions"]:
            review = {"image_id": record["image_id"], **deepcopy(prediction)}
            review.setdefault("review_status", "pending")
            for field in ("reviewed_by", "reviewed_at", "override_reason", "override_label"):
                review.setdefault(field, None)
            reviews.append(review)
    confidences: list[float] = []
    low_confidence_items: list[dict[str, Any]] = []
    for record in records.values():
        for prediction in record["fruit_predictions"]:
            confidence = float(prediction["confidence"])
            confidences.append(confidence)
            if confidence < threshold:
                low_confidence_items.append(
                    {
                        "image_id": record["image_id"],
                        "crop_id": prediction["crop_id"],
                        "predicted_class": prediction["predicted_class"],
                        "confidence": confidence,
                        "oleocellosis_probability": prediction["oleocellosis_probability"],
                    }
                )

    return {
        "schema_version": "1.0",
        "sample_id": sample_id,
        "lot_id": lot_id,
        "pallet_id": pallet_id,
        "vision_summary": {
            "images_processed": len(records),
            "image_ids": list(records),
            "total_fruits": total,
            "oleocellosis_count": affected,
            "confirmed_oleocellosis_count": affected,
            "raw_oleocellosis_count": raw_affected,
            "suspected_oleocellosis_count": raw_affected,
            "pending_review_count": pending,
            "rejected_oleocellosis_count": rejected,
            "review_completed": pending == 0,
            "vision_review": reviews,
            # Conservar precisión hasta aplicar las reglas. Solo la interfaz y
            # el reporte deben redondear para presentación.
            "oleocellosis_pct": 100.0 * affected / total if total else 0.0,
            "raw_oleocellosis_pct": 100.0 * raw_affected / total if total else 0.0,
            "mean_confidence": math.fsum(confidences) / len(confidences) if confidences else None,
            "low_confidence_threshold": threshold,
            "low_confidence_count": len(low_confidence_items),
            "low_confidence_items": low_confidence_items,
            "duplicate_image_ids_ignored": duplicates,
        },
    }
