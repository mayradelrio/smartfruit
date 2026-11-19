"""Explicit physical-box closure and descriptive manifest count comparison.

Vision JSONs keep their existing contract. These application metadata describe
one physical box; a pallet's accumulated sample is never compared to one box.
"""

from __future__ import annotations

import re
from typing import Any

BOX_STATUSES = ("capturing", "completed")
COMPARISON_STATUSES = ("matched", "shortage", "excess", "unavailable", "selection_required")


def _expected_count(value: Any) -> int | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not text:
        return None
    if isinstance(value, bool) or not re.fullmatch(r"\d+(?:\.0+)?", text):
        raise ValueError("El count declarado de la línea seleccionada debe ser un entero positivo.")
    count = int(text.split(".", 1)[0])
    return count if count > 0 else None


def summarize_box_inspection(
    metadata: Any,
    vision_summary: dict[str, Any],
    reception: dict[str, Any] | None = None,
    *,
    require_completed: bool = False,
) -> dict[str, Any]:
    """Recompute all measurements; client-supplied totals are never trusted.

    ``manifest_record_index`` selects a zero-based row from the already validated
    sample reception. Without a selector, a uniform count/size is unambiguous.
    Capturing boxes can be summarized, but cannot produce an operational report.
    A real count difference never prevents an explicitly completed inspection.
    """
    if not isinstance(metadata, dict):
        raise ValueError("box_inspection: registrar los datos de la caja física.")
    box_id = metadata.get("sample_box_id")
    if not isinstance(box_id, str) or not box_id.strip():
        raise ValueError("sample_box_id: completar el identificador de la caja.")
    status = metadata.get("status")
    if status not in BOX_STATUSES:
        raise ValueError("La caja debe estar capturing o completed.")
    coverage = metadata.get("coverage_confirmed", False)
    if not isinstance(coverage, bool):
        raise ValueError("Confirmar explícitamente la cobertura física de la caja.")
    if status == "completed" and not coverage:
        raise ValueError("Finalizar la caja requiere confirmar toda su cobertura sin repetir frutos.")
    if require_completed and status != "completed":
        raise ValueError(f"{box_id}: finaliza la inspección de la caja antes de evaluar.")

    actual = vision_summary["total_fruits"]
    if status == "completed" and actual <= 0:
        raise ValueError("No se puede finalizar una caja sin frutos evaluados por Vision.")
    rows = reception.get("records", []) if isinstance(reception, dict) else []
    index = metadata.get("manifest_record_index")
    if index is not None and (
        isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(rows)
    ):
        raise ValueError("Selecciona una línea válida del manifiesto de esta paleta.")
    expected = None
    selected = None
    comparison = "unavailable"
    if rows:
        if index is None and len(rows) == 1:
            index = 0
        if index is not None:
            selected = rows[index]
        else:
            variants = {
                (str(row.get("expected_count_per_box", "")).strip(),
                 str(row.get("size_declared", "")).strip())
                for row in rows
            }
            if len(variants) == 1:
                selected = rows[0]
            else:
                comparison = "selection_required"
        if selected is not None:
            expected = _expected_count(selected.get("expected_count_per_box"))
    if comparison == "selection_required" and require_completed:
        raise ValueError(
            f"{box_id}: selecciona la línea del manifiesto de la caja; "
            "la paleta contiene distintos tamaños o counts declarados."
        )
    difference = actual - expected if expected is not None else None
    if difference is not None:
        comparison = "matched" if difference == 0 else "shortage" if difference < 0 else "excess"
    return {
        "sample_box_id": box_id.strip(),
        "status": status,
        "coverage_confirmed": coverage,
        "manifest_record_index": index,
        "size_declared": selected.get("size_declared", "") if selected else "",
        "images_processed": vision_summary["images_processed"],
        "actual_count": actual,
        "expected_count_per_box": expected,
        "count_difference": difference,
        "count_deviation_pct": 100.0 * difference / expected if expected is not None else None,
        "missing_count": max(-difference, 0) if difference is not None else None,
        "excess_count": max(difference, 0) if difference is not None else None,
        "oleocellosis_count": vision_summary["oleocellosis_count"],
        "oleocellosis_pct": vision_summary["oleocellosis_pct"],
        "comparison_status": comparison,
    }
