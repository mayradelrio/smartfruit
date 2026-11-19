"""Descriptive lot totals in the existing QC terminology, without new rules.

This module aggregates observed quantities.  It does not infer the business's
historical Level Flag, assign lot severity, or change per-sample recommendations.
"""

from collections.abc import Mapping, Sequence

from .inspection import DEFECT_COLUMNS


def _count(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label}: debe ser una cantidad entera observada no negativa.")
    if positive and value == 0:
        raise ValueError(f"{label}: la muestra debe contener frutos.")
    return value


def _percentage_text(value):
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    # Avoid describing a positive incidence as 0% in unusually large samples.
    return f"{value:.8g}" if value > 0 and text == "0" else text


def build_lot_summary(samples):
    """Return counts, weighted percentages and a descriptive Reason for a lot.

    ``samples`` are final-report sample dictionaries with ``pallet_id`` and
    complete ``qc_fields``. If legacy data has several samples for one pallet,
    counts are accumulated per pallet before computing affected-pallet ranges.
    All sixteen defect columns remain represented, including those with no
    implemented severity rule. Missing observations are rejected, never zeroed.
    """
    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)) or not samples:
        raise ValueError("El resumen de lote necesita al menos una muestra QC.")

    pallets = {}
    sample_count = 0
    for sample in samples:
        if not isinstance(sample, Mapping) or not isinstance(sample.get("qc_fields"), Mapping):
            raise ValueError("Cada muestra debe contener sus campos QC observados.")
        fields = sample["qc_fields"]
        pallet_id = sample.get("pallet_id")
        if not isinstance(pallet_id, str) or not pallet_id.strip():
            raise ValueError("Cada muestra necesita N° PALLET como identificador de texto.")
        pallet_id = pallet_id.strip()
        if fields.get("pallet_id") not in (None, "", pallet_id):
            raise ValueError("N° PALLET no coincide con el pallet asociado a la muestra.")
        size = _count(fields.get("sample_count"), f"{pallet_id}: Sample", positive=True)
        sample_count += size
        counts = pallets.setdefault(pallet_id, dict.fromkeys((c["key"] for c in DEFECT_COLUMNS), 0))
        for column in DEFECT_COLUMNS:
            key, label = column["key"], column["label"]
            value = _count(fields.get(key), f"{pallet_id}: {label}")
            if value > size:
                raise ValueError(f"{pallet_id}: {label} supera Sample ({size}).")
            counts[key] += value

    pallet_count = len(pallets)
    defects, reasons = [], []
    total_incidents = 0
    for column in DEFECT_COLUMNS:
        key, label = column["key"], column["label"]
        per_pallet = [counts[key] for counts in pallets.values()]
        positive_counts = [value for value in per_pallet if value > 0]
        count = sum(per_pallet)
        percentage = 100.0 * count / sample_count
        minimum = min(positive_counts, default=0)
        maximum = max(positive_counts, default=0)
        affected = len(positive_counts)
        defects.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "pct": percentage,
                "affected_pallets": affected,
                "inspected_pallets": pallet_count,
                "min_count": minimum,
                "max_count": maximum,
            }
        )
        total_incidents += count
        if count:
            interval = str(minimum) if minimum == maximum else f"{minimum} - {maximum}"
            reasons.append(
                f"Up to {interval} {label} in {affected} of {pallet_count} pallets. "
                f"Total {count} / {sample_count} fruits ({_percentage_text(percentage)}%)."
            )

    return {
        "pallet_count": pallet_count,
        "sample_count": sample_count,
        "defects": defects,
        "total_defect_incidents": total_incidents,
        # Several defects may affect the same fruit; this sum can exceed 100%.
        "total_combined_pct": 100.0 * total_incidents / sample_count,
        "level_flag_status": "INSPECTOR_REQUIRED",
        "generated_reason": "\n".join(reasons)
        if reasons
        else "No defects recorded in the inspected samples.",
    }
