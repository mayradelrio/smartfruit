"""Inferencia local con los pesos existentes, sin entrenar ni descargar modelos.

Los recortes individuales se clasifican directamente con ResNet18. Las fotos
completas requieren además YOLO para localizar los frutos antes de clasificarlos.
Las importaciones pesadas se aplazan para poder usar un Python de Vision separado
del proceso web. El CLI intercambia JSON con ese proceso.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import threading
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from .local_files import write_json_atomic
from .vision import VISION_CLASSES, validate_vision_record

DEFAULT_MODELS_DIR = Path(__file__).resolve().parents[2] / "data/local/vision_input/models"
CLASSIFIER_FILENAME = "resnet18_freeze_layer1_layer2_best.pth"
DETECTOR_FILENAME = "best.pt"
INPUT_KINDS = ("fruit_crop", "scene")
PIPELINE = "resnet18_individual_fruit_or_yolo_boxes_resnet18"
DEFAULT_BATCH_SIZE = 32
MAX_BATCH_SIZE = 128
_INFERENCE_LOCK = threading.RLock()
_PROGRESS_STATE = threading.local()


def _model_dir(models_dir: str | Path | None) -> Path:
    return Path(models_dir) if models_dir is not None else DEFAULT_MODELS_DIR


def get_runtime_status(
    models_dir: str | Path | None = None, input_kind: str = "fruit_crop"
) -> dict[str, Any]:
    """Comprueba disponibilidad sin cargar pesos ni importar librerías pesadas."""
    _check_kind(input_kind)
    models = _model_dir(models_dir)
    common_dependencies = {"torch": "torch", "torchvision": "torchvision", "Pillow": "PIL"}
    missing_common = [
        name for name, module in common_dependencies.items()
        if importlib.util.find_spec(module) is None
    ]
    classifier_missing = not (models / CLASSIFIER_FILENAME).is_file()
    detector_missing = not (models / DETECTOR_FILENAME).is_file()
    ultralytics_missing = importlib.util.find_spec("ultralytics") is None
    crop_ready = not missing_common and not classifier_missing
    scene_ready = crop_ready and not detector_missing and not ultralytics_missing
    missing_dependencies = list(missing_common)
    missing_models = [CLASSIFIER_FILENAME] if classifier_missing else []
    if input_kind == "scene":
        if ultralytics_missing:
            missing_dependencies.append("ultralytics")
        if detector_missing:
            missing_models.append(DETECTOR_FILENAME)
    return {
        "ready": bool(crop_ready if input_kind == "fruit_crop" else scene_ready),
        "input_kind": input_kind,
        "capabilities": {"fruit_crop": bool(crop_ready), "scene": bool(scene_ready)},
        "missing_dependencies": missing_dependencies,
        "missing_models": missing_models,
        "pipeline": PIPELINE,
        "python_executable": sys.executable,
    }


def _check_kind(input_kind: str) -> None:
    if input_kind not in INPUT_KINDS:
        raise ValueError("input_kind debe ser fruit_crop o scene")


def _class_indices(class_to_idx: Any) -> dict[str, int]:
    if not isinstance(class_to_idx, Mapping) or set(class_to_idx) != VISION_CLASSES:
        raise ValueError("El clasificador debe definir con_oleocelosis y sin_oleocelosis")
    if any(type(index) is not int for index in class_to_idx.values()):
        raise ValueError("Los índices de las clases deben ser enteros")
    if set(class_to_idx.values()) != {0, 1}:
        raise ValueError("El clasificador debe tener dos índices distintos: 0 y 1")
    return dict(class_to_idx)


def _signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=2)
def _load_classifier(signature: tuple[str, int, int]) -> tuple[Any, Any, dict[str, int]]:
    import codecs

    import numpy as np
    import torch
    from torchvision import models, transforms

    # El checkpoint del notebook incluye una métrica numpy.float64. Se permite
    # únicamente ese tipo de metadato, manteniendo weights_only=True.
    try:
        from numpy._core.multiarray import scalar
    except ImportError:
        from numpy.core.multiarray import scalar
    safe_types = [scalar, np.dtype, type(np.dtype(np.float64)), codecs.encode]
    with torch.serialization.safe_globals(safe_types):
        checkpoint = torch.load(signature[0], map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict) or checkpoint.get("model_name") != "resnet18":
        raise ValueError("El checkpoint debe corresponder a la arquitectura resnet18")
    class_to_idx = _class_indices(checkpoint.get("class_to_idx"))
    if checkpoint.get("positive_class", "con_oleocelosis") != "con_oleocelosis":
        raise ValueError("La clase positiva del checkpoint no corresponde a oleocelosis")
    model = models.resnet18(weights=None)
    model.fc = torch.nn.Linear(model.fc.in_features, 2)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    return model, transform, class_to_idx


@lru_cache(maxsize=2)
def _load_detector(signature: tuple[str, int, int]) -> Any:
    # La configuración de Ultralytics queda junto a los datos locales del proyecto.
    config_dir = Path(signature[0]).parent.parent / "runtime"
    os.environ.setdefault("YOLO_CONFIG_DIR", str(config_dir))
    os.environ.setdefault("YOLO_OFFLINE", "true")
    from ultralytics import YOLO

    return YOLO(signature[0])


def _predictions_from_probabilities(
    probabilities: Sequence[Sequence[float]], class_to_idx: Mapping[str, int], image_id: str
) -> list[dict[str, Any]]:
    """Interpreta softmax respetando el orden de clases guardado en los pesos."""
    indices = _class_indices(class_to_idx)
    names_by_index = {index: name for name, index in indices.items()}
    positive_index = indices["con_oleocelosis"]
    predictions = []
    for i, row in enumerate(probabilities, start=1):
        if len(row) != 2 or any(not math.isfinite(p) or not 0 <= p <= 1 for p in row):
            raise ValueError("El clasificador devolvió probabilidades no válidas")
        if not math.isclose(sum(row), 1.0, abs_tol=0.0001):
            raise ValueError("Las probabilidades del clasificador no suman uno")
        predicted_index = max(range(2), key=lambda index: row[index])
        predictions.append({
            "crop_id": f"{image_id}_L{i:02d}.jpg",
            "predicted_class": names_by_index[predicted_index],
            "oleocellosis_probability": float(row[positive_index]),
            "confidence": float(row[predicted_index]),
        })
    return predictions


def _record(
    image_id: str, partition: str, predictions: list[dict[str, Any]], metadata: dict[str, Any]
) -> dict[str, Any]:
    total = len(predictions)
    affected = sum(p["predicted_class"] == "con_oleocelosis" for p in predictions)
    result = {
        "image_id": image_id,
        "partition": partition,
        "total_fruits": total,
        "oleocellosis_count": affected,
        "oleocellosis_pct": 100.0 * affected / total if total else 0.0,
        "mean_confidence": (
            math.fsum(p["confidence"] for p in predictions) / total if total else None
        ),
        "fruit_predictions": predictions,
        "inference": metadata,
    }
    validate_vision_record(result)
    return result


def _image_input(
    image_path: str | Path, image_id: str | None, partition: str, input_kind: str,
) -> tuple[Path, str]:
    _check_kind(input_kind)
    path = Path(image_path)
    if not path.is_file():
        raise ValueError(f"No se encontró la imagen: {path.name}")
    identifier = image_id if image_id is not None else path.stem
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("image_id debe ser texto no vacío")
    if not isinstance(partition, str) or not partition.strip():
        raise ValueError("partition debe ser texto no vacío")
    return path, identifier


def _open_rgb(path: Path) -> Any:
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(path) as original:
            return ImageOps.exif_transpose(original).convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"No se pudo abrir la imagen {path.name}") from exc


def _classifier_metadata(
    path: Path, image_size: Sequence[int], class_to_idx: Mapping[str, int], input_kind: str,
) -> dict[str, Any]:
    return {
        "pipeline": PIPELINE,
        "input_kind": input_kind,
        "source_filename": path.name,
        "classifier": CLASSIFIER_FILENAME,
        "class_to_idx": class_to_idx,
        "image_size": list(image_size),
        "device": "cpu",
    }


def _request_batch_size(request: Mapping[str, Any]) -> int:
    if "batch_size" in request:
        value = request["batch_size"]
    else:
        raw = os.getenv("SMARTFRUIT_VISION_BATCH_SIZE", str(DEFAULT_BATCH_SIZE)).strip()
        value = int(raw) if raw.isascii() and raw.isdecimal() else None
    if type(value) is not int or not 1 <= value <= MAX_BATCH_SIZE:
        raise ValueError(
            f"batch_size / SMARTFRUIT_VISION_BATCH_SIZE debe ser un entero entre 1 y {MAX_BATCH_SIZE}"
        )
    return value


def _infer_crop_batch(
    images: Sequence[Mapping[str, Any]], *, models_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Classify bounded one-fruit inputs together, retaining one record per photo."""
    if not 1 <= len(images) <= MAX_BATCH_SIZE:
        raise ValueError(f"El lote de recortes debe contener entre 1 y {MAX_BATCH_SIZE} imágenes")
    prepared = [
        (*_image_input(item["path"], item.get("image_id"), item["partition"], "fruit_crop"),
         item["partition"])
        for item in images
    ]
    status = get_runtime_status(models_dir, "fruit_crop")
    if not status["ready"]:
        missing = status["missing_models"] + status["missing_dependencies"]
        raise RuntimeError("Vision no está disponible: faltan " + ", ".join(missing))

    import torch

    models = _model_dir(models_dir)
    with _INFERENCE_LOCK:
        _publish_phase("LOADING_MODEL")
        model, transform, class_to_idx = _load_classifier(
            _signature(models / CLASSIFIER_FILENAME)
        )
        tensors, sizes = [], []
        for path, _, _ in prepared:
            image = _open_rgb(path)
            try:
                tensors.append(transform(image))
                sizes.append((image.width, image.height))
            finally:
                image.close()
        _publish_phase("CLASSIFYING")
        with torch.inference_mode():
            probabilities = torch.softmax(model(torch.stack(tensors)), dim=1).cpu().tolist()
        if len(probabilities) != len(prepared):
            raise ValueError("El clasificador no devolvió una predicción por fotografía")
        return [
            _record(
                identifier, partition,
                _predictions_from_probabilities([row], class_to_idx, identifier),
                _classifier_metadata(path, size, class_to_idx, "fruit_crop"),
            )
            for (path, identifier, partition), size, row in zip(prepared, sizes, probabilities)
        ]


def infer_image(
    image_path: str | Path,
    *,
    image_id: str | None = None,
    partition: str = "capture",
    models_dir: str | Path | None = None,
    input_kind: str = "scene",
) -> dict[str, Any]:
    """Procesa una foto con pesos locales y devuelve el contrato Vision vigente.

    ``fruit_crop`` cuenta exactamente un fruto por fotografía. ``scene`` detecta
    cajas con YOLO (640px, confianza 0.25) y clasifica sus recortes con ResNet18.
    No usa anotaciones/labels del dataset ni resultados JSON precalculados.
    """
    path, identifier = _image_input(image_path, image_id, partition, input_kind)
    status = get_runtime_status(models_dir, input_kind)
    if not status["ready"]:
        missing = status["missing_models"] + status["missing_dependencies"]
        raise RuntimeError("Vision no está disponible: faltan " + ", ".join(missing))

    import torch
    image = _open_rgb(path)

    models = _model_dir(models_dir)
    with _INFERENCE_LOCK:
        _publish_phase("LOADING_MODEL")
        model, transform, class_to_idx = _load_classifier(
            _signature(models / CLASSIFIER_FILENAME)
        )
        regions: list[tuple[int, int, int, int]] = []
        detector_confidences: list[float] = []
        if input_kind == "fruit_crop":
            regions.append((0, 0, image.width, image.height))
        else:
            detector = _load_detector(_signature(models / DETECTOR_FILENAME))
            _publish_phase("DETECTING")
            detected = detector.predict(
                source=image, imgsz=640, conf=0.25, agnostic_nms=True,
                device="cpu", verbose=False, save=False,
            )[0]
            if detected.boxes is not None:
                for box in detected.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().tolist()
                    region = (
                        max(0, math.floor(x1)), max(0, math.floor(y1)),
                        min(image.width, math.ceil(x2)), min(image.height, math.ceil(y2)),
                    )
                    if region[2] > region[0] and region[3] > region[1]:
                        regions.append(region)
                        detector_confidences.append(float(box.conf.item()))
        _publish_phase("CLASSIFYING", len(regions))
        probabilities: list[list[float]] = []
        with torch.inference_mode():
            for start in range(0, len(regions), 32):
                batch = torch.stack([
                    transform(image.crop(region)) for region in regions[start:start + 32]
                ])
                probabilities.extend(torch.softmax(model(batch), dim=1).cpu().tolist())
        predictions = _predictions_from_probabilities(probabilities, class_to_idx, identifier)

    metadata = _classifier_metadata(path, (image.width, image.height), class_to_idx, input_kind)
    if input_kind == "scene":
        metadata.update({
            "detector": DETECTOR_FILENAME, "detector_imgsz": 640,
            "detector_confidence_threshold": 0.25, "class_agnostic_nms": True,
            "detector_confidences": detector_confidences,
            "fruit_boxes_xyxy": [list(region) for region in regions],
        })
    return _record(identifier, partition, predictions, metadata)


def _atomic_json(path: Path, content: Any) -> None:
    write_json_atomic(path, content)


def _publish_phase(phase: str, detected_fruits: int | None = None) -> None:
    state = getattr(_PROGRESS_STATE, "value", None)
    if state is None:
        return
    state["phase"] = phase
    if detected_fruits is not None:
        state["detected_fruits"] = state.get("previous_fruits", 0) + detected_fruits
    path = state.get("path")
    if path is not None:
        try:
            _atomic_json(path, {k: v for k, v in state.items()
                                if k not in ("path", "previous_fruits")})
        except OSError:
            pass


def _write_progress(path: Path | None, completed: int, total: int) -> None:
    state = getattr(_PROGRESS_STATE, "value", None)
    values = {"completed": completed, "total": total}
    if state is not None:
        state.update(values)
        values.update({key: state[key] for key in ("phase", "detected_fruits") if key in state})
    if path is not None:
        try:
            _atomic_json(path, values)
        except OSError:
            # El progreso es telemetría: un bloqueo del lector/sincronizador no
            # debe descartar las predicciones ni impedir guardar el resultado.
            pass


def run_request(request: Mapping[str, Any]) -> dict[str, Any]:
    previous = getattr(_PROGRESS_STATE, "value", None)
    _PROGRESS_STATE.value = {
        "path": Path(request["progress_path"]) if request.get("progress_path") else None,
        "phase": "LOADING_MODEL", "completed": 0, "total": len(request.get("images") or []),
    }
    try:
        return _run_request(request)
    finally:
        _PROGRESS_STATE.value = previous


def _run_request(request: Mapping[str, Any]) -> dict[str, Any]:
    images = request.get("images")
    if not isinstance(images, list) or not images:
        raise ValueError("La solicitud debe incluir una lista de imágenes")
    progress_path = Path(request["progress_path"]) if request.get("progress_path") else None
    batch_size = _request_batch_size(request)
    normalized = []
    for item in images:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise ValueError("Cada imagen debe indicar su path")
        kind = item.get("input_kind", request.get("input_kind", "scene"))
        _check_kind(kind)
        normalized.append({
            "path": item["path"], "image_id": item.get("image_id"),
            "partition": item.get("partition", request.get("partition", "capture")),
            "input_kind": kind,
        })
    records = []
    _write_progress(progress_path, 0, len(images))
    index = 0
    while index < len(normalized):
        state = _PROGRESS_STATE.value
        state["previous_fruits"] = sum(record["total_fruits"] for record in records)
        item = normalized[index]
        if item["input_kind"] == "fruit_crop":
            end = index + 1
            while (end < len(normalized) and end - index < batch_size
                   and normalized[end]["input_kind"] == "fruit_crop"):
                end += 1
            records.extend(_infer_crop_batch(normalized[index:end], models_dir=request.get("models_dir")))
            index = end
        else:
            records.append(infer_image(
                item["path"], image_id=item["image_id"], partition=item["partition"],
                input_kind=item["input_kind"], models_dir=request.get("models_dir"),
            ))
            index += 1
        state["detected_fruits"] = sum(record["total_fruits"] for record in records)
        _write_progress(progress_path, len(records), len(images))
    return {"records": records, "pipeline": PIPELINE}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inferencia local SmartFruit")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--models-dir", type=Path)
    parser.add_argument("--input-kind", choices=INPUT_KINDS, default="fruit_crop")
    args = parser.parse_args(argv)
    if args.status:
        print(json.dumps(get_runtime_status(args.models_dir, args.input_kind)))
        return 0
    if args.request is None or args.output is None:
        parser.error("Se requieren --request y --output")
    try:
        request = json.loads(args.request.read_text(encoding="utf-8-sig"))
        if not isinstance(request, Mapping):
            raise ValueError("La solicitud de Vision debe ser un objeto JSON")
        result = run_request(request)
        _atomic_json(args.output, result)
    except Exception as exc:
        try:
            _atomic_json(args.output, {"error": str(exc)})
        except OSError as write_error:
            print(f"No se pudo guardar el resultado de Vision: {write_error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
