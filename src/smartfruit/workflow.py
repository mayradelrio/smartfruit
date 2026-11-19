"""Coordinación del flujo completo; recomendación por muestra/pallet."""

from .business_rules import evaluate_business_severity
from .decision import build_final_report
from .inspection import build_sample, validate_header, validate_qc_summary
from .lot_inspection import validate_lot_reception
from .lot_summary import build_lot_summary
from .predictive import attach_predictive
from .report_evidence import attach_report_evidence
from .vision import validate_vision_source_overlap


def evaluate_inspection(payload, use_predictive=False, provider=None, boundary_policy="higher"):
    if not isinstance(payload, dict):
        raise ValueError("La inspección debe ser un objeto JSON.")
    reason_source = payload.get("reason_source")
    if "reason_source" in payload and reason_source not in ("defect_summary", "inspector"):
        raise ValueError("reason_source debe ser 'defect_summary' o 'inspector'.")
    header = validate_header(payload.get("qc_header"))
    inputs = payload.get("samples")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("Agregar al menos una muestra para inspeccionar.")
    lot_reception = None
    if "lot_reception" in payload:
        lot_reception = validate_lot_reception(payload["lot_reception"], inputs, header["lot_id"])
    samples = []
    sample_ids, image_ids = set(), set()
    for data in inputs:
        record = build_sample(data, header["lot_id"], boundary_policy)
        if record["sample_id"] in sample_ids:
            raise ValueError(f"sample_id repetido: {record['sample_id']}.")
        sample_ids.add(record["sample_id"])
        current_images = set(record["vision_summary"]["image_ids"])
        overlap = current_images & image_ids
        if overlap:
            raise ValueError(
                f"Las fotografías {sorted(overlap)} están asignadas a más de una muestra."
            )
        image_ids.update(current_images)
        record = evaluate_business_severity(record, boundary_policy)
        record = attach_predictive(record, enabled=use_predictive, provider=provider)
        samples.append(build_final_report(record))
    validate_vision_source_overlap(
        source for data in inputs for source in data["vision_records"]
    )
    observations = payload.get("observations", "")
    if not isinstance(observations, str):
        raise ValueError("Las observaciones del reporte deben ser texto.")
    # Este contenedor QC nuevo no modifica el contrato de Vision/Predictive.
    # No calcula una recomendación de lote a partir de muestras por suposición.
    report = {
        "schema_version": "1.1",
        "lot_id": header["lot_id"],
        "qc_header": header,
        "samples": samples,
        "human_confirmation_required": True,
        "inspector_name": "",
        "inspector_confirmed": False,
        "confirmed_at": None,
        "observations": observations,
    }
    if "qc_summary" in payload:
        report["qc_summary"] = validate_qc_summary(payload["qc_summary"])
    if lot_reception is not None:
        report["lot_reception"] = lot_reception
    report["lot_summary"] = build_lot_summary(samples)
    report["generated_reason"] = report["lot_summary"]["generated_reason"]
    if "reason_source" in payload:
        report["reason_source"] = reason_source
        if reason_source == "defect_summary":
            report["qc_header"]["reason"] = report["generated_reason"]
    return attach_report_evidence(report, payload)
