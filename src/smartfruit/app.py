"""Interfaz local y API del MVP; iniciar con smartfruit o python -m smartfruit.app."""

import json
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response

from .additional_review import add_additional_review
from .decision import confirm_inspection
from .image_binding import validate_vision_import
from .inspection import HEADER_FIELDS, MANUAL_DEFECTS, QC_COLUMNS, QC_SUMMARY_FIELDS, RULE_COVERAGE
from .predictive import use_predictive_from_env
from .print_report import render_qc_print
from .reception import (
    load_reception_manifest,
    manifest_summary,
    resolve_reception,
    resolve_reception_lot,
)
from .report_evidence import attach_report_evidence
from .vision_capture import VisionCapture
from .vision_validation import build_adjudicated_dataset, calculate_vision_metrics
from .workflow import evaluate_inspection


def _xlsx(report):
    # La exportación no exige pesos ni módulos de entrenamiento.
    from .qc_report import export_qc_xlsx

    return export_qc_xlsx(report)


def create_app(reports_dir=None, use_predictive=None, vision_capture=None):
    enabled = use_predictive_from_env() if use_predictive is None else use_predictive
    destination = Path(reports_dir or os.getenv("SMARTFRUIT_REPORTS_DIR", "reports"))
    capture = vision_capture if vision_capture is not None else VisionCapture()

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            capture.close()

    app = FastAPI(title="SmartFruit QC", version="0.2.0", lifespan=lifespan)
    app.state.vision_capture = capture

    async def payload_from(request):
        def reject_nonfinite(value):
            raise ValueError(f"Número JSON no finito: {value}")

        try:
            payload = json.loads(await request.body(), parse_constant=reject_nonfinite)
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, "El cuerpo debe ser JSON válido.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(422, "La inspección debe ser un objeto JSON.")
        return payload

    def evaluate(payload):
        try:
            report = evaluate_inspection(payload, use_predictive=enabled)
            return attach_report_evidence(report, payload, capture.report_evidence_resolver())
        except (ValueError, TypeError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(files("smartfruit").joinpath("web/index.html").read_text("utf-8"))

    @app.get("/api/config")
    def config():
        return {
            "use_predictive": bool(enabled),
            "boundary_policy": "higher",
            "header_fields": deepcopy(HEADER_FIELDS),
            "qc_columns": deepcopy(QC_COLUMNS),
            "manual_defects": deepcopy(MANUAL_DEFECTS),
            "rule_coverage": deepcopy(RULE_COVERAGE),
            "qc_summary_fields": deepcopy(QC_SUMMARY_FIELDS),
        }

    @app.get("/assets/{name}")
    def client_asset(name: str):
        if name == "agroperu-logo.png":
            return Response(
                files("smartfruit").joinpath("resources/branding/agroperu-logo.png").read_bytes(),
                media_type="image/png",
            )
        if name not in ("drafts.js", "field_sources.js", "vision_defaults.js", "vision_capture.js",
                        "vision_review.js"):
            raise HTTPException(404, "Recurso no encontrado.")
        return Response(
            files("smartfruit").joinpath("web", name).read_text("utf-8"),
            media_type="application/javascript",
        )

    @app.get("/api/vision/photos")
    def vision_photos():
        return capture.catalog()

    @app.get("/api/vision/photos/{photo_id}/image")
    def vision_photo(photo_id: str):
        try:
            return FileResponse(capture.photo_path(photo_id))
        except KeyError as exc:
            raise HTTPException(404, "Fotografía no encontrada.") from exc

    @app.post("/api/vision/jobs", status_code=202)
    async def start_vision(request: Request):
        try:
            return await run_in_threadpool(capture.submit, await payload_from(request))
        except (ValueError, TypeError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/vision/jobs/{job_id}")
    def vision_job(job_id: str):
        try:
            return capture.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Trabajo de Vision no encontrado.") from exc

    @app.get("/api/vision/jobs/{job_id}/photos/{photo_id}/image")
    def vision_evidence(job_id: str, photo_id: str):
        try:
            return FileResponse(capture.job_photo_path(job_id, photo_id))
        except KeyError as exc:
            raise HTTPException(404, "Fotografía no encontrada en esta revisión.") from exc

    @app.post("/api/vision/import")
    async def import_vision(request: Request):
        try:
            return validate_vision_import(await payload_from(request))
        except (ValueError, TypeError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/vision/validation")
    async def vision_validation(request: Request):
        payload = await payload_from(request)
        try:
            records = payload.get("vision_records")
            adjudications = payload.get("adjudications", [])
            if not isinstance(records, list) or not isinstance(adjudications, list):
                raise ValueError("Proporcionar vision_records y adjudications como listas.")
            dataset = build_adjudicated_dataset(records, adjudications)
            return {"dataset": dataset, "metrics": calculate_vision_metrics(dataset)}
        except (ValueError, TypeError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/inspection/additional-review")
    async def additional_review(request: Request):
        try:
            result = add_additional_review(await payload_from(request), use_predictive=enabled)
            result["report"] = attach_report_evidence(
                result["report"], result["capture"], capture.report_evidence_resolver()
            )
            return result
        except (ValueError, TypeError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/inspection/additional-review/preview")
    async def preview_additional_review(request: Request):
        try:
            return validate_vision_import(await payload_from(request), additional_review=True)
        except (ValueError, TypeError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/demo")
    def demo():
        records = [
            json.loads(
                files("smartfruit").joinpath(f"resources/vision/{image}.json").read_text("utf-8")
            )
            for image in ("IMG_6426", "IMG_6427", "IMG_6428")
        ]
        return {
            "records": records,
            "qc_header": {
                "lot_id": "LOT_DEMO_001",
                "inspection_date": datetime.now(ZoneInfo("America/Lima")).date().isoformat(),
                "remarks": "DEMO: fotografías de evaluación; datos QC manuales simulados.",
            },
            "sample_id": "SAMPLE_DEMO_001",
            "pallet_id": "PALLET_DEMO_01",
        }

    @app.post("/api/evaluate")
    async def preview(request: Request):
        return evaluate(await payload_from(request))

    @app.post("/api/reception/manifest")
    async def import_manifest(request: Request):
        payload = await payload_from(request)
        try:
            source = payload.get("manifest_csv")
            if not isinstance(source, str):
                raise ValueError("Seleccionar un archivo CSV de recepción.")
            return manifest_summary(load_reception_manifest(source))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/reception/resolve")
    @app.post("/api/reception/lot")
    async def scan_pallet(request: Request):
        payload = await payload_from(request)
        try:
            source = payload.get("manifest_csv")
            if not isinstance(source, str):
                raise ValueError("Primero cargar el manifiesto CSV.")
            lot_id = payload.get("lot_id")
            resolver = (
                resolve_reception_lot if request.url.path.endswith("/lot") else resolve_reception
            )
            return resolver(
                load_reception_manifest(source),
                payload.get("scan_input"),
                None if lot_id in (None, "") else lot_id,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/report/print", response_class=HTMLResponse)
    async def print_draft(request: Request):
        return HTMLResponse(render_qc_print(evaluate(await payload_from(request))))

    @app.post("/api/export")
    async def draft(request: Request):
        report = evaluate(await payload_from(request))
        return Response(
            content=_xlsx(report),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="smartfruit_qc_borrador.xlsx"'},
        )

    @app.post("/api/finalize")
    async def finalize(request: Request):
        payload = await payload_from(request)
        report = evaluate(payload)
        try:
            report = confirm_inspection(
                report,
                payload.get("inspector_name"),
                payload.get("final_decisions"),
                payload.get("confirmed"),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        # Recalcular con la captura actual: nunca confiar en una recomendación
        # calculada o en un estado de confirmación enviado desde el navegador.
        data = _xlsx(report)
        report_id = str(uuid4())
        destination.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=destination))
        try:
            (temporary / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), "utf-8"
            )
            (temporary / "source.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), "utf-8"
            )
            (temporary / "report.xlsx").write_bytes(data)
            temporary.rename(destination / report_id)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return {
            "report_id": report_id,
            "report": report,
            "downloads": {
                "xlsx": f"/api/reports/{report_id}/xlsx",
                "json": f"/api/reports/{report_id}/json",
                "print": f"/api/reports/{report_id}/print",
            },
        }

    @app.get("/api/reports/{report_id}/{kind}")
    def download(report_id: str, kind: str):
        try:
            if str(UUID(report_id)) != report_id or kind not in ("xlsx", "json", "print"):
                raise ValueError
        except ValueError as exc:
            raise HTTPException(404, "Reporte no encontrado.") from exc
        path = destination / report_id / f"report.{'json' if kind == 'print' else kind}"
        if not path.is_file():
            raise HTTPException(404, "Reporte no encontrado.")
        if kind == "print":
            report = json.loads(path.read_text("utf-8"))
            return HTMLResponse(render_qc_print(report))
        media_type = (
            "application/json"
            if kind == "json"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        return FileResponse(
            path, media_type=media_type, filename=f"smartfruit_qc_{report_id}.{kind}"
        )

    return app


def main():
    import uvicorn

    # Local por defecto; no se publica la información QC en una interfaz externa.
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.getenv("PORT", "3000")))


if __name__ == "__main__":
    main()
