"""Adaptador de transporte para ejecutar el MVP Python existente en el navegador.

No define defectos, thresholds ni decisiones: importa los módulos originales.
La persistencia de la captura y del reporte corresponde a IndexedDB en bridge.js.
"""

import base64
from copy import deepcopy
from datetime import datetime
from importlib.resources import files
import json
from uuid import UUID
from zoneinfo import ZoneInfo

from smartfruit.additional_review import add_additional_review
from smartfruit.decision import confirm_inspection
from smartfruit.image_binding import validate_vision_import
from smartfruit.inspection import (
    HEADER_FIELDS,
    MANUAL_DEFECTS,
    QC_COLUMNS,
    QC_SUMMARY_FIELDS,
    RULE_COVERAGE,
)
from smartfruit.qc_report import export_qc_xlsx
from smartfruit.print_report import render_qc_print
from smartfruit.reception import (
    load_reception_manifest,
    manifest_summary,
    resolve_reception,
    resolve_reception_lot,
)
from smartfruit.workflow import evaluate_inspection


JSON_TYPE = "application/json"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _envelope(body, status=200, content_type=JSON_TYPE, **extra):
    return {"status": status, "body": body, "content_type": content_type, **extra}


def _reject_nonfinite(value):
    raise ValueError(f"Número JSON no finito: {value}")


def _payload(body_json):
    try:
        payload = json.loads(body_json, parse_constant=_reject_nonfinite)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("El cuerpo debe ser JSON válido.") from exc
    if not isinstance(payload, dict):
        raise ValueError("La inspección debe ser un objeto JSON.")
    return payload


def _dispatch(method, path, body_json, report_id):
    if path == "/api/inspection/additional-review/preview":
        if method != "POST":
            return _envelope({"detail": "Método no permitido."}, status=405)
        return _envelope(validate_vision_import(_payload(body_json), additional_review=True))
    if path == "/api/inspection/additional-review":
        if method != "POST":
            return _envelope({"detail": "Método no permitido."}, status=405)
        return _envelope(add_additional_review(_payload(body_json), use_predictive=False))
    if path == "/api/vision/import":
        if method != "POST":
            return _envelope({"detail": "Método no permitido."}, status=405)
        return _envelope(validate_vision_import(_payload(body_json)))
    if path == "/api/report/print-saved":
        if method != "POST":
            return _envelope({"detail": "Método no permitido."}, status=405)
        # Transporte local: el bridge toma este reporte de su IndexedDB; no es
        # una operación de confirmación ni una escritura al almacenamiento.
        return _envelope(
            render_qc_print(_payload(body_json)["report"]), content_type="text/html; charset=utf-8"
        )
    if path in ("/api/reception/manifest", "/api/reception/resolve", "/api/reception/lot"):
        if method != "POST":
            return _envelope({"detail": "Método no permitido."}, status=405)
        payload = _payload(body_json)
        source = payload.get("manifest_csv")
        if not isinstance(source, str):
            raise ValueError("Primero cargar el manifiesto CSV.")
        records = load_reception_manifest(source)
        if path.endswith("/manifest"):
            return _envelope(manifest_summary(records))
        lot_id = payload.get("lot_id")
        resolver = resolve_reception_lot if path.endswith("/lot") else resolve_reception
        return _envelope(
            resolver(
                records,
                payload.get("scan_input"),
                None if lot_id in (None, "") else lot_id,
            )
        )
    if method == "GET" and path == "/api/config":
        return _envelope(
            {
                "use_predictive": False,
                "boundary_policy": "higher",
                "header_fields": deepcopy(HEADER_FIELDS),
                "qc_columns": deepcopy(QC_COLUMNS),
                "manual_defects": deepcopy(MANUAL_DEFECTS),
                "rule_coverage": deepcopy(RULE_COVERAGE),
                "qc_summary_fields": deepcopy(QC_SUMMARY_FIELDS),
            }
        )
    if method == "GET" and path == "/api/demo":
        records = [
            json.loads(
                files("smartfruit").joinpath(f"resources/vision/{image}.json").read_text("utf-8")
            )
            for image in ("IMG_6426", "IMG_6427", "IMG_6428")
        ]
        return _envelope(
            {
                "records": records,
                "qc_header": {
                    "lot_id": "LOT_DEMO_001",
                    "inspection_date": datetime.now(ZoneInfo("America/Lima")).date().isoformat(),
                    "remarks": "DEMO: fotografías de evaluación; datos QC manuales simulados.",
                },
                "sample_id": "SAMPLE_DEMO_001",
                "pallet_id": "PALLET_DEMO_01",
            }
        )
    if path not in ("/api/evaluate", "/api/export", "/api/finalize", "/api/report/print"):
        return _envelope({"detail": "Ruta no encontrada."}, status=404)
    if method != "POST":
        return _envelope({"detail": "Método no permitido."}, status=405)
    payload = _payload(body_json)
    report = evaluate_inspection(payload, use_predictive=False)
    if path == "/api/evaluate":
        return _envelope(report)
    if path == "/api/report/print":
        return _envelope(render_qc_print(report), content_type="text/html; charset=utf-8")
    if path == "/api/export":
        return _envelope(
            base64.b64encode(export_qc_xlsx(report)).decode("ascii"),
            content_type=XLSX_TYPE,
            encoding="base64",
        )
    report = confirm_inspection(
        report,
        payload.get("inspector_name"),
        payload.get("final_decisions"),
        payload.get("confirmed"),
    )
    if str(UUID(report_id)) != report_id:
        raise ValueError("No se pudo asignar un identificador válido al reporte.")
    workbook = base64.b64encode(export_qc_xlsx(report)).decode("ascii")
    result = {
        "report_id": report_id,
        "report": report,
        "downloads": {
            "xlsx": f"/api/reports/{report_id}/xlsx",
            "json": f"/api/reports/{report_id}/json",
            "print": f"/api/reports/{report_id}/print",
        },
    }
    # No devolver éxito a la UI antes de que bridge.js complete la transacción.
    return _envelope(
        result,
        storage={
            "id": report_id,
            "report": report,
            "source": payload,
            "xlsx_base64": workbook,
        },
    )


def smartfruit_browser_api(method, path, body_json="", report_id=""):
    """Devuelve un sobre de transporte JSON; no modifica los contratos del MVP."""
    try:
        response = _dispatch(method, path, body_json, report_id)
    except (ValueError, TypeError, OverflowError) as exc:
        response = _envelope({"detail": str(exc)}, status=422)
    except Exception:
        response = _envelope(
            {
                "detail": "No se pudo completar el reporte. Conserva la captura e inténtalo de nuevo."
            },
            status=500,
        )
    return json.dumps(response, ensure_ascii=False, allow_nan=False)
