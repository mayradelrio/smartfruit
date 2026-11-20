"""Self-contained photographic evidence derived only from validated Vision inputs.

No filesystem access occurs here. The local app can supply a resolver restricted
to its Vision catalog and immutable jobs; the browser-only runtime supplies none.
Pillow is imported only when real image bytes are available.
"""

from __future__ import annotations

import base64
import hashlib
import math
from copy import deepcopy
from io import BytesIO
from typing import Any, Callable

from .vision_review import review_status

ImageResolver = Callable[[dict[str, Any], int, dict[str, str]], dict[str, Any] | None]
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_EDGE = 1024


def _image_attachment(source, record, prediction_index):
    """Decode actual pixels, optionally crop aligned detections, strip metadata."""
    if not isinstance(source, dict):
        return None
    raw = source.get("image_bytes")
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_IMAGE_BYTES:
        return None
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        return None
    try:
        with Image.open(BytesIO(raw)) as original:
            if original.width * original.height > MAX_IMAGE_PIXELS:
                return None
            image = ImageOps.exif_transpose(original).convert("RGB")
            view = "fruit_crop" if source.get("input_kind") == "fruit_crop" else "scene"
            metadata = record.get("inference")
            metadata = metadata if isinstance(metadata, dict) else {}
            regions = metadata.get("fruit_boxes_xyxy")
            if (
                view == "scene" and isinstance(regions, list)
                and len(regions) == len(record["fruit_predictions"])
                and metadata.get("image_size") == [image.width, image.height]
            ):
                region = regions[prediction_index]
                if (
                    isinstance(region, (list, tuple)) and len(region) == 4
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                            and math.isfinite(v) for v in region)
                ):
                    x1, y1, x2, y2 = region
                    if 0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height:
                        image = image.crop((math.floor(x1), math.floor(y1),
                                            math.ceil(x2), math.ceil(y2)))
                        view = "fruit_crop"
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            output = BytesIO()
            # A newly encoded RGB image carries no source EXIF, paths or names.
            image.save(output, format="JPEG", quality=80, optimize=True, exif=b"")
            normalized = output.getvalue()
            return {
                "image_data_url": "data:image/jpeg;base64," + base64.b64encode(normalized).decode(),
                "width": image.width, "height": image.height, "view": view,
                "_digest": hashlib.sha256(normalized).hexdigest(),
            }
    except (OSError, ValueError, TypeError, UnidentifiedImageError, Image.DecompressionBombError):
        return None


def _box_records(sample):
    history = sample.get("review_history")
    if isinstance(history, dict) and isinstance(history.get("initial"), dict):
        for entry in [history["initial"], *history.get("additional", [])]:
            box = entry.get("box_inspection")
            yield box.get("sample_box_id") if isinstance(box, dict) else None, entry.get(
                "vision_records", []
            )
    else:
        box = sample.get("box_inspection")
        yield box.get("sample_box_id") if isinstance(box, dict) else None, sample.get(
            "vision_records", []
        )


def attach_report_evidence(report, payload, resolver: ImageResolver | None = None):
    """Rebuild attachments from QC-confirmed positives, ignoring injected report data.

    Missing images leave an explicit availability summary. A complete group photo
    is labeled honestly when individual positive crops cannot be established.
    """
    result = deepcopy(report)
    inputs = {sample["sample_id"].strip(): sample for sample in payload.get("samples", [])}
    for sample in result.get("samples", []):
        source_sample = inputs.get(sample["sample_id"], {})
        context = {key: str(sample.get(key) or result.get(key) or "")
                   for key in ("lot_id", "pallet_id", "sample_id")}
        photos, positive_fruits, attached_fruits = [], 0, 0
        seen_images = set()
        for box_id, records in _box_records(source_sample):
            for record in records:
                if record["image_id"] in seen_images:
                    continue
                seen_images.add(record["image_id"])
                positives = [index for index, prediction in enumerate(record["fruit_predictions"])
                             if prediction["predicted_class"] == "con_oleocelosis"
                             and review_status(prediction) == "confirmed"
                             and prediction.get("qc_included") is not False]
                positive_fruits += len(positives)
                scene_photos = {}
                for index in positives:
                    prediction = record["fruit_predictions"][index]
                    audit = {"detection_index": index + 1,
                             "review_status": prediction.get("review_status", "pending"),
                             "override_label": prediction.get("override_label")}
                    source = resolver(record, index, context) if resolver is not None else None
                    attachment = _image_attachment(source, record, index)
                    if attachment is None:
                        continue
                    digest = attachment.pop("_digest")
                    if attachment["view"] == "scene":
                        existing = scene_photos.get(digest)
                        if existing is not None:
                            existing["affected_fruits"] += 1
                            existing["vision_reviews"].append(audit)
                            attached_fruits += 1
                            continue
                    opaque_id = hashlib.sha256(
                        (record["image_id"] + ":" + str(index) + ":" + digest)
                        .encode("utf-8")
                    ).hexdigest()[:24]
                    photo = {
                        "evidence_id": opaque_id,
                        "sample_box_id": box_id,
                        "defect": "oleocellosis",
                        "affected_fruits": 1,
                        "vision_reviews": [audit],
                        "caption": (
                            "Oleocelosis confirmada por revisión QC."
                            if attachment["view"] == "fruit_crop" else
                            "Foto grupal con oleocelosis confirmada por revisión QC."
                        ),
                        **attachment,
                    }
                    photos.append(photo)
                    if photo["view"] == "scene":
                        scene_photos[digest] = photo
                    attached_fruits += 1
        unavailable = positive_fruits - attached_fruits
        status = (
            "no_defects" if positive_fruits == 0 else
            "unavailable" if not photos else "partial" if unavailable else "available"
        )
        sample["evidence_photos"] = photos
        sample["evidence_summary"] = {
            "status": status, "positive_fruits": positive_fruits,
            "attached_fruits": attached_fruits, "attached_photos": len(photos),
            "unavailable_fruits": unavailable,
            "message": (
                "No hay oleocelosis confirmada por QC." if status == "no_defects" else
                "No hay fotografías disponibles de la oleocelosis confirmada por QC."
                if status == "unavailable" else
                "Parte de la evidencia fotográfica no está disponible."
                if status == "partial" else "Evidencia de oleocelosis confirmada por QC adjunta."
            ),
        }
    return result
