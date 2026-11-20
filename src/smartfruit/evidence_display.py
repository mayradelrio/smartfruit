"""Presentation of resolved defect photos, without paths or source image names."""

from __future__ import annotations

import base64
import binascii


def evidence_photos(sample):
    """Accept only embedded raster photos already identified as oleocellosis."""
    if (sample.get("inspection_summary") or {}).get("oleocellosis_count") == 0:
        return []
    result = []
    for photo in sample.get("evidence_photos") or []:
        if not isinstance(photo, dict) or photo.get("defect") != "oleocellosis":
            continue
        reviews = photo.get("vision_reviews") or []
        if reviews and not any(
            review.get("review_status") == "confirmed" and review.get("qc_included") is not False
            for review in reviews
        ):
            continue
        affected = photo.get("affected_fruits")
        if isinstance(affected, bool) or not isinstance(affected, int) or affected <= 0:
            continue
        url = photo.get("image_data_url")
        if not isinstance(url, str) or len(url) > 8_000_000:
            continue
        prefix, separator, encoded = url.partition(",")
        if not separator or prefix not in ("data:image/jpeg;base64", "data:image/png;base64"):
            continue
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            continue
        valid = (
            prefix == "data:image/png;base64" and data.startswith(b"\x89PNG\r\n\x1a\n")
        ) or (
            prefix == "data:image/jpeg;base64" and data.startswith(b"\xff\xd8\xff")
        )
        if valid:
            result.append((photo, url, data))
    return result


def evidence_caption(sample, photo, number):
    pallet = sample.get("pallet_id") or sample.get("qc_fields", {}).get("pallet_id")
    parts = [f"Paleta {pallet}" if pallet else "Paleta sin identificar"]
    if photo.get("sample_box_id"):
        parts.append(f"Caja {photo['sample_box_id']}")
    reviews = photo.get("vision_reviews") or []
    parts.append("Oleocelosis · sospecha Vision" if reviews else "Oleocelosis")
    if reviews:
        confirmed = sum(review.get("review_status") == "confirmed" for review in reviews)
        rejected = sum(review.get("review_status") == "rejected" for review in reviews)
        parts.append(f"QC: {confirmed} confirmadas, {rejected} rechazadas")
    parts.append("Fruto observado" if photo.get("view") == "fruit_crop" else "Grupo con detección")
    parts.append(f"Fotografía {number}")
    return " · ".join(parts)


def evidence_notice(sample, attached_count):
    """Describe unavailable positive evidence without relabeling healthy fruit."""
    if (sample.get("inspection_summary") or {}).get("oleocellosis_count") == 0:
        return ""
    summary = sample.get("evidence_summary") or {}
    positive = summary.get("positive_fruits")
    if not isinstance(positive, (int, float)) or isinstance(positive, bool):
        positive = (sample.get("inspection_summary") or {}).get("oleocellosis_count", 0)
    if not positive or positive <= 0:
        return ""
    if not attached_count:
        return "No se adjuntaron fotografías de los frutos con oleocelosis detectada."
    if summary.get("status") == "partial" or (summary.get("unavailable_fruits") or 0) > 0:
        return "Se adjunta la evidencia disponible; algunos frutos con oleocelosis no tienen fotografía adjunta."
    return ""
