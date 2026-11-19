"""Standalone, escaped QC print view; PDF is saved through the browser dialog."""

from __future__ import annotations

import base64
import math
from datetime import date, datetime
from functools import lru_cache
from html import escape
from importlib.resources import files
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from .evidence_display import evidence_caption, evidence_notice, evidence_photos
from .inspection import QC_COLUMNS

_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_DECISIONS = {"STANDARD", "EXTEND", "COMPLETE", "EXPAND", "ESCALATE"}
_SUMMARY_COLUMNS = {
    0: "label_brand",
    3: "packing_date",
    7: "plu_coo",
    9: "open_rating",
    10: "color_rating",
}


def _text(value, missing=""):
    if value is None or value == "":
        value = missing
    return escape(str(value), quote=True)


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


def _amount(value):
    number = _number(value)
    return "" if number is None else format(number, ".12g")


def _pct(value):
    number = _number(value)
    return "" if number is None else f"{number:.2f}%"


def _date(value):
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError:
            pass
    if isinstance(value, (date, datetime)):
        value = value.strftime("%m-%d-%y")
    return _text(value)


@lru_cache(maxsize=1)
def _template_profile():
    """Read labels, header fills/rotation, widths and the existing logo without Pillow."""
    resource = files("smartfruit").joinpath("resources/qc_template.xlsx")
    with ZipFile(BytesIO(resource.read_bytes())) as archive:
        worksheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        styles = ET.fromstring(archive.read("xl/styles.xml"))
        fills = styles.find("s:fills", _NS)
        formats = styles.find("s:cellXfs", _NS)
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(item.itertext()) for item in root]
        row = worksheet.find(".//s:row[@r='15']", _NS)
        headers = []
        for cell in row:
            if cell.attrib.get("t") == "inlineStr":
                label = "".join(cell.find("s:is", _NS).itertext())
            else:
                raw = cell.find("s:v", _NS)
                label = shared[int(raw.text)] if raw is not None else ""
            fmt = formats[int(cell.attrib.get("s", "0"))]
            alignment = fmt.find("s:alignment", _NS)
            fill = fills[int(fmt.attrib.get("fillId", "0"))]
            foreground = fill.find("s:patternFill/s:fgColor", _NS)
            rgb = foreground.attrib.get("rgb", "") if foreground is not None else ""
            color = (
                "#" + rgb[-6:]
                if len(rgb) in (6, 8) and all(char in "0123456789abcdefABCDEF" for char in rgb)
                else "#ffffff"
            )
            headers.append(
                {
                    "label": label,
                    "fill": color,
                    "rotated": alignment is not None
                    and alignment.attrib.get("textRotation") == "90",
                }
            )
        widths = [8.43] * 29
        columns = worksheet.find("s:cols", _NS)
        if columns is not None:
            for column in columns:
                for index in range(int(column.attrib["min"]) - 1, int(column.attrib["max"])):
                    if index < 29:
                        widths[index] = float(column.attrib.get("width", 8.43))
        image_name = next(
            name for name in sorted(archive.namelist()) if name.startswith("xl/media/")
        )
        image_type = "image/png" if image_name.endswith(".png") else "image/jpeg"
        logo = f"data:{image_type};base64," + base64.b64encode(archive.read(image_name)).decode(
            "ascii"
        )
    return {"headers": headers[:29], "widths": widths, "logo": logo}


def _totals(report):
    samples = report["samples"]
    counts = {}
    for column in QC_COLUMNS[12:]:
        values = [_number(sample["qc_fields"].get(column["key"])) for sample in samples]
        counts[column["key"]] = sum(values) if all(value is not None for value in values) else None
    values = [_number(sample["qc_fields"].get("sample_count")) for sample in samples]
    denominator = sum(values) if all(value is not None for value in values) else None
    provided = report.get("lot_summary") or {}
    if _number(provided.get("sample_count")) is not None:
        denominator = provided["sample_count"]
    percentages = {}
    provided_defects = {item["key"]: item for item in provided.get("defects", [])}
    for key in counts:
        supplied = provided_defects.get(key, {})
        if _number(supplied.get("count")) is not None:
            counts[key] = supplied["count"]
        percentages[key] = (
            supplied.get("pct")
            if _number(supplied.get("pct")) is not None
            else (
                100 * counts[key] / denominator
                if counts[key] is not None and denominator is not None and denominator > 0
                else None
            )
        )
    incidents = (
        sum(counts.values()) if all(value is not None for value in counts.values()) else None
    )
    combined = (
        100 * incidents / denominator
        if (incidents is not None and denominator is not None and denominator > 0)
        else None
    )
    if _number(provided.get("total_defect_incidents")) is not None:
        incidents = provided["total_defect_incidents"]
    if _number(provided.get("total_combined_pct")) is not None:
        combined = provided["total_combined_pct"]
    pallet_count = len(
        {sample.get("pallet_id") or sample["qc_fields"].get("pallet_id") for sample in samples}
    )
    if _number(provided.get("pallet_count")) is not None:
        pallet_count = provided["pallet_count"]
    return {
        "sample_count": denominator,
        "pallet_count": pallet_count,
        "counts": counts,
        "percentages": percentages,
        "incidents": incidents,
        "combined": combined,
    }


def _confirmed(report):
    return (
        report.get("inspector_confirmed") is True
        and bool(report.get("inspector_name"))
        and bool(report.get("confirmed_at"))
        and all(
            sample.get("inspector_confirmed") is True
            and sample.get("inspector_final_decision") in _DECISIONS
            for sample in report["samples"]
        )
    )


def _entry(label, value):
    return f"<dt>{_text(label)}</dt><dd>{_text(value, 'Pendiente')}</dd>"


def _review_action(value):
    return "EXTEND" if value == "EXPAND" else value


def _box_inspections(sample):
    boxes = sample.get("box_inspections") or []
    if not boxes:
        return ""
    comparisons = {
        "matched": "Conteo detectado igual al declarado",
        "shortage": "Conteo detectado menor que el declarado",
        "excess": "Conteo detectado mayor que el declarado",
        "unavailable": "Sin conteo esperado disponible",
        "selection_required": "Pendiente de seleccionar la línea del manifiesto",
    }
    result = [
        '<section class="box-inspections"><h4>Inspección por caja · esperado y detectado</h4>'
    ]
    for box in boxes:
        result.append(f"<h4>Caja {_text(box.get('sample_box_id'), 'Sin identificador')}</h4><dl>")
        result.append(_entry(
            "Estado de captura", "Finalizada" if box.get("status") == "completed" else "En captura",
        ))
        result.append(_entry(
            "Cobertura completa confirmada",
            "Sí" if box.get("coverage_confirmed") is True else "Pendiente",
        ))
        for label, key in (
            ("Fotografías procesadas de la caja", "images_processed"),
            ("Frutos esperados por caja · manifiesto", "expected_count_per_box"),
            ("Frutos detectados en la caja", "actual_count"),
            ("Diferencia · detectados menos esperados", "count_difference"),
            ("Unidades menos detectadas", "missing_count"),
            ("Unidades más detectadas", "excess_count"),
        ):
            result.append(_entry(label, _amount(box.get(key)) or "No disponible"))
        result.append(_entry(
            "Desviación respecto al esperado", _pct(box.get("count_deviation_pct")) or "No disponible",
        ))
        result.append(_entry(
            "Comparación de conteo", comparisons.get(box.get("comparison_status"), "No disponible"),
        ))
        result.append("</dl>")
    result.append("</section>")
    return "".join(result)


def _review_quantities(fields, vision, *, accumulated=False):
    denominator = _number(fields.get("sample_count"))
    affected = _number(fields.get("oleocellosis"))
    percentage = (
        100 * affected / denominator
        if affected is not None and denominator is not None and denominator > 0
        else None
    )
    suffix = "acumulados" if accumulated else "de esta revisión"
    result = ["<dl>", _entry(f"Sample · frutos {suffix}", _amount(denominator))]
    result.append(
        _entry(
            "Oleocellosis acumulada" if accumulated else "Oleocellosis · esta revisión",
            f"{_amount(affected)} frutos · {_pct(percentage)}",
        )
    )
    defects, observed = [], []
    for column in QC_COLUMNS[12:]:
        if column["key"] == "oleocellosis":
            continue
        count = _number(fields.get(column["key"]))
        observed.append(count)
        if count is not None and count > 0:
            pct = 100 * count / denominator if denominator is not None and denominator > 0 else None
            defects.append(f"{column['label']}: {_amount(count)} frutos ({_pct(pct)})")
    result.append(
        _entry(
            "Otros defectos acumulados" if accumulated else "Otros defectos · esta revisión",
            "\n".join(defects) if defects else (
                "Sin otros defectos registrados." if all(value == 0 for value in observed) else "Pendiente"
            ),
        )
    )
    result.append(
        _entry(
            "Fotografías acumuladas" if accumulated else "Fotografías de esta revisión",
            vision.get("images_processed", len(vision.get("image_ids") or [])),
        )
    )
    result.append("</dl>")
    return "".join(result)


def _review_history(sample):
    history = sample.get("review_history")
    if not history or not history.get("additional"):
        return ""
    pallet = sample.get("pallet_id") or sample["qc_fields"].get("pallet_id")
    result = [
        f'<section class="review-history"><h4>Historial de revisiones · Paleta {_text(pallet)}</h4>',
        "<h4>Revisión inicial · primera caja</h4>",
    ]
    initial = history["initial"]
    result.append(_review_quantities(initial["qc_fields"], initial["inspection_summary"]))
    result.append("<dl>")
    result.append(_entry("Sugerencia tras revisión inicial", _review_action(initial.get("system_recommendation"))))
    result.append("</dl>")
    for review in history["additional"]:
        result.append(f"<h4>Revisión adicional {_text(review['review_number'])} · caja adicional</h4><dl>")
        result.append(_entry("Acción del inspector que amplió la inspección", _review_action(review.get("trigger_decision"))))
        result.append(_entry("Sugerencia antes de ampliar", _review_action(review.get("system_recommendation_before"))))
        result.append("</dl>")
        result.append(_review_quantities(review["qc_fields"], review["inspection_summary"]))
        result.append("<dl>")
        result.append(_entry("Observaciones de la revisión adicional", review.get("observations")))
        result.append(_entry("Sugerencia después de sumar la revisión", _review_action(review.get("system_recommendation_after"))))
        result.append("</dl>")
    result.append(f"<h4>Acumulado de la paleta {_text(pallet)} · todas las revisiones</h4>")
    result.append(_review_quantities(sample["qc_fields"], sample.get("inspection_summary") or {}, accumulated=True))
    result.append("</section>")
    return "".join(result)


def _photo_evidence(sample):
    photos = evidence_photos(sample)
    notice = evidence_notice(sample, len(photos))
    if not photos and not notice:
        return ""
    result = ['<section class="photo-evidence"><h4>Evidencia fotográfica · oleocelosis detectada</h4>']
    if notice:
        result.append(f"<p>{_text(notice)}</p>")
    for number, (photo, url, _) in enumerate(photos, start=1):
        caption = _text(evidence_caption(sample, photo, number))
        result.append(
            f'<figure><img src="{_text(url)}" alt="{caption}"><figcaption>{caption}</figcaption></figure>'
        )
    result.append("</section>")
    return "".join(result)


def _smartfruit(report, totals, confirmed):
    result = ['<section class="smartfruit" aria-label="SmartFruit"><h2>SmartFruit</h2>']
    status = "CONFIRMADO" if confirmed else "BORRADOR · pendiente de confirmación del inspector"
    result.append(f'<p class="report-status">{status}</p><dl>')
    result.append(_entry("Inspector", report.get("inspector_name")))
    timestamp = report.get("confirmed_at") if confirmed else None
    if timestamp:
        try:
            moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if moment.tzinfo is not None:
                timestamp = moment.astimezone(ZoneInfo("America/Lima")).strftime(
                    "%d/%m/%Y %H:%M:%S (America/Lima)"
                )
        except (ValueError, AttributeError):
            pass
    result.append(_entry("Confirmación del reporte", timestamp))
    result.append(_entry("Observaciones", report.get("observations")))
    for pallet in (report.get("lot_reception") or {}).get("pallets", []):
        state = pallet.get("inspection_status", "PENDING")
        value = "No inspeccionada · SKIPPED" if state == "SKIPPED" else state
        if pallet.get("skip_reason"):
            value += " · " + pallet["skip_reason"]
        result.append(_entry(f"Paleta {pallet.get('pallet_id', '')}", value))
    result.append("</dl>")
    if report.get("lot_summary"):
        result.append('<section class="lot-summary"><h3>Resumen del lote</h3><dl>')
        result.append(_entry("Paletas inspeccionadas", _amount(totals["pallet_count"])))
        result.append(_entry("Sample · frutos evaluados", _amount(totals["sample_count"])))
        result.append(_entry("Incidencias de defectos", _amount(totals["incidents"])))
        result.append(_entry("Total Percent Combined", _pct(totals["combined"])))
        proposed = report["lot_summary"].get("generated_reason")
        if proposed:
            result.append(_entry("Motivo propuesto a partir del lote", proposed))
        result.append("</dl></section>")
    for sample in report["samples"]:
        pallet = sample.get("pallet_id") or sample["qc_fields"].get("pallet_id")
        result.append(
            f'<section class="pallet-decision"><h3>N° PALLET {_text(pallet)} · {_text(sample.get("sample_id"))}</h3><dl>'
        )
        severity = sample.get("business_severity") or {}
        result.append(_entry("Nivel / severidad resultante", severity.get("business_max_level")))
        recommendation = sample.get("final_recommendation") or severity.get("recommendation")
        if sample.get("review_history") or sample.get("review_choice"):
            recommendation = _review_action(recommendation)
        result.append(_entry("Recomendación SmartFruit", recommendation))
        result.append(_entry("Versión de reglas", sample.get("rules_engine_version")))
        if sample.get("defect_dominance"):
            result.append(_entry("Dominancia · procedencia", sample["defect_dominance"]))
        reasons = sample.get("recommendation_reasons", severity.get("reasons", []))
        result.append(_entry("Motivo", "; ".join(str(reason) for reason in reasons)))
        predictive = sample.get("predictive") or {}
        enabled = predictive.get("enabled") is True
        result.append(_entry("Predictive", "ON - Experimental" if enabled else "OFF"))
        if enabled:
            result.append(
                _entry(
                    "predicted_loss_pct",
                    _pct(predictive.get("predicted_loss_pct")) or "No disponible",
                )
            )
        decision = sample.get("inspector_final_decision")
        if not confirmed and sample.get("review_choice"):
            result.append(_entry("Estado inspector (pendiente de confirmación)", _review_action(sample["review_choice"])))
        if sample.get("review_history") or sample.get("review_choice"):
            decision = _review_action(decision)
        if decision and not confirmed:
            decision = str(decision) + " · pendiente de confirmación"
        result.append(_entry("Decisión final del inspector", decision))
        result.append(
            _entry("Confirmación del inspector", "Confirmada" if confirmed else "Pendiente")
        )
        result.append(_entry("Observaciones", sample.get("observations")))
        vision = sample.get("inspection_summary") or {}
        result.append(_entry("Frutos evaluados por Vision", _amount(vision.get("total_fruits"))))
        result.append(_entry("Oleocelosis confirmada QC", _amount(vision.get("oleocellosis_count"))))
        result.append(_entry("Sospechosos del modelo", _amount(vision.get("suspected_oleocellosis_count"))))
        result.append(_entry("Porcentaje de oleocelosis", _pct(vision.get("oleocellosis_pct"))))
        result.append(_entry(
            "Fotografías procesadas", vision.get("images_processed", len(vision.get("image_ids") or [])),
        ))
        coverage = sample.get("rule_coverage") or {}
        result.append(
            _entry(
                "Defectos con regla",
                ", ".join(str(value) for value in coverage.get("evaluated", [])),
            )
        )
        result.append(
            _entry(
                "Defectos sin regla implementada",
                ", ".join(str(value) for value in coverage.get("not_evaluated", [])),
            )
        )
        result.append("</dl>")
        reviews = vision.get("vision_review") or []
        if reviews:
            result.append("<details><summary>Revisión QC de Vision</summary><table><thead><tr>"
                          "<th>Imagen / fruto</th><th>Predicción original</th><th>Probabilidad</th>"
                          "<th>Revisión</th><th>Corrección</th><th>Inspector / fecha</th>"
                          "</tr></thead><tbody>")
            for prediction in reviews:
                result.append("<tr>" + "".join(f"<td>{_text(value)}</td>" for value in (
                    f"{prediction.get('image_id', '')} / {prediction.get('crop_id', '')}",
                    prediction.get("predicted_class"), prediction.get("oleocellosis_probability"),
                    prediction.get("review_status"),
                    " · ".join(str(prediction.get(key) or "")
                               for key in ("override_label", "override_reason")),
                    " · ".join(str(prediction.get(key) or "")
                               for key in ("reviewed_by", "reviewed_at")),
                )) + "</tr>")
            result.append("</tbody></table></details>")
        result.append(_box_inspections(sample))
        result.append(_review_history(sample))
        result.append(_photo_evidence(sample))
        reception = sample.get("reception")
        if reception:
            result.append("<h4>Recepción · Checker + ERP</h4><dl>")
            result.append(_entry("Lectura escaneada", reception.get("scan_input")))
            for record in reception.get("records", []):
                for label, key in (
                    ("AgroPeru Lot Number", "lot_id"),
                    ("N° PALLET", "pallet_id"),
                    ("Label", "label_brand"),
                    ("Size declarado", "size_declared"),
                    ("Frutos DECLARADOS por caja", "expected_count_per_box"),
                    ("Cajas recibidas", "boxes_received"),
                    ("Peso recibido", "qty_received_weight"),
                    ("Procedencia", "data_origin"),
                    ("Referencia", "source_record"),
                ):
                    value = record.get(key)
                    if value is None or (isinstance(value, str) and not value.strip()):
                        value = "No registrado"
                    result.append(_entry(label, value))
            result.append("</dl>")
        result.append("</section>")
    result.append(
        '<p class="incidents-note">Los totales combinados suman incidencias de defectos. Un fruto puede presentar varios defectos; no representan frutos únicos afectados.</p></section>'
    )
    return "".join(result)


_CSS = """
@page { size: A3 landscape; margin: 10mm; }
* { box-sizing: border-box; }
body { color: #111; font-family: Arial, sans-serif; font-size: 9pt; margin: 20px; }
.toolbar { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
.toolbar button { padding: 10px 16px; cursor: pointer; font: inherit; }
.print-note { font-size: 9pt; }
.page { max-width: 400mm; margin: auto; }
.inspection-title { font-size: 18pt; letter-spacing: .04em; margin: 0 0 5mm; color: #20342d; }
.qc-header { display: grid; grid-template-columns: 29% 24% 37% 10%; gap: 0; min-height: 53mm; }
.logo { width: 94%; height: auto; margin: 7mm 2mm 0 0; }
.header-fields { margin: 0; padding: 0 3mm; }
.header-fields div { display: grid; grid-template-columns: 50% 50%; min-height: 10mm; }
.header-fields dt { font-weight: bold; }
.header-fields dd { margin: 0; }
.remarks { padding: 0 3mm; white-space: pre-wrap; overflow-wrap: anywhere; }
.remarks p { margin: 0 0 2mm; }
.remarks-text { min-height: 37mm; }
.side-fields { padding-left: 2mm; }
.side-fields dt { font-weight: bold; }
.side-fields dd { margin: 0 0 5mm; text-align: center; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; }
th, td { border: .2mm solid #222; padding: 1mm .5mm; text-align: center; overflow-wrap: anywhere; }
.qc-table { font-size: 7pt; }
.qc-table thead { display: table-header-group; }
.qc-table tr { break-inside: avoid; }
.groups th { background: #fff; font-size: 10pt; font-weight: bold; border: .4mm double #222; }
.column-labels th { height: 32mm; font-weight: normal; vertical-align: middle; }
.column-labels .rotated span { writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap; }
.qc-data td { height: 5mm; }
.qc-totals td { font-weight: bold; }
.qc-sums[hidden] { display: none; }
.total-label { text-align: right; font-weight: bold; }
.report-status { font-weight: bold; }
.smartfruit { border-top: .5mm solid #222; margin-top: 8mm; padding-top: 3mm; }
.smartfruit h2 { font-size: 14pt; margin: 0 0 3mm; }
.smartfruit h3 { font-size: 11pt; margin: 4mm 0 2mm; }
.smartfruit dl { display: grid; grid-template-columns: 28% 72%; margin: 0; }
.smartfruit dt, .smartfruit dd { border-bottom: .15mm solid #ccc; margin: 0; padding: 1.2mm; white-space: pre-wrap; overflow-wrap: anywhere; }
.smartfruit dt { font-weight: bold; }
.pallet-decision { break-inside: avoid; margin-top: 4mm; }
.incidents-note { font-size: 8pt; }
.photo-evidence figure { margin: 3mm 0; break-inside: avoid; }
.photo-evidence img { max-width: 160mm; max-height: 95mm; width: auto; height: auto; object-fit: contain; }
.photo-evidence figcaption { font-size: 8pt; margin-top: 1mm; }
@media print {
  body { margin: 0; }
  .toolbar { display: none; }
  .page { max-width: none; }
  th { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
}
"""


def render_qc_print(report: dict) -> str:
    """Return self-contained HTML; the browser's print dialog can save it as PDF."""
    if (
        not isinstance(report, dict)
        or not isinstance(report.get("samples"), list)
        or not report["samples"]
    ):
        raise ValueError("El QC Report imprimible necesita al menos una muestra.")
    if any(
        not isinstance(sample, dict) or not isinstance(sample.get("qc_fields"), dict)
        for sample in report["samples"]
    ):
        raise ValueError("Cada muestra debe contener sus campos QC.")
    profile = _template_profile()
    header = report.get("qc_header") or {}
    confirmed = _confirmed(report)
    totals = _totals(report)
    status = "CONFIRMADO" if confirmed else "BORRADOR"
    title = f"QUALITY INSPECTION · {header.get('lot_id') or report.get('lot_id') or ''} · {status}"
    result = [
        f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_text(title)}</title><style>{_CSS}</style></head><body>'
    ]
    result.append(
        '<div class="toolbar"><button type="button" onclick="window.print()">Imprimir / Guardar PDF</button><p class="print-note">Abre el diálogo de impresión del navegador y elige Guardar como PDF.</p></div><main class="page"><h1 class="inspection-title">QUALITY INSPECTION</h1>'
    )
    result.append(
        f'<header class="qc-header"><div><img class="logo" src="{profile["logo"]}" alt="AgroPeru"></div><dl class="header-fields">'
    )
    for label, key in (
        ("Inspection Date:", "inspection_date"),
        ("Vessel:", "vessel"),
        ("Container:", "container"),
        ("AgroPeru Lot Number:", "lot_id"),
        ("Country Of Origin:", "country_origin"),
    ):
        value = (
            _date(header.get(key))
            if key == "inspection_date"
            else _text(header.get(key, report.get("lot_id") if key == "lot_id" else ""))
        )
        result.append(f"<div><dt>{label}</dt><dd>{value}</dd></div>")
    result.append(
        f'</dl><div class="remarks"><p><strong>Remarks:</strong> <span class="level-flag">Level Flag: {_text(header.get("Level_Flag"))}</span></p><p class="remarks-text">{_text(header.get("remarks"))}</p><p><strong>Reason:</strong> {_text(header.get("reason"))}</p></div><dl class="side-fields">'
    )
    for label, key in (("Grade:", "grade"), ("Color:", "color"), ("PLU%:", "plu_pct")):
        result.append(f"<dt>{label}</dt><dd>{_text(header.get(key))}</dd>")
    result.append('</dl></header><table class="qc-table" aria-label="QC Report"><colgroup>')
    width_sum = sum(profile["widths"])
    result.extend(
        f'<col style="width:{100 * width / width_sum:.4f}%">' for width in profile["widths"]
    )
    result.append(
        '</colgroup><thead><tr class="groups"><th colspan="9">General Information</th><th colspan="12">Condition</th><th colspan="7">Quality</th><th></th></tr><tr class="column-labels">'
    )
    for item in profile["headers"]:
        cls = ' class="rotated"' if item["rotated"] else ""
        result.append(
            f'<th scope="col"{cls} style="background:{item["fill"]}"><span>{_text(item["label"])}</span></th>'
        )
    result.append("</tr></thead><tbody>")
    for sample in report["samples"]:
        fields = sample["qc_fields"]
        result.append('<tr class="qc-data">')
        for column in QC_COLUMNS:
            value = (
                _date(fields.get(column["key"]))
                if column["key"] == "packing_date"
                else _text(fields.get(column["key"]))
            )
            result.append(f"<td>{value}</td>")
        n = _number(fields.get("sample_count"))
        counts = [_number(fields.get(column["key"])) for column in QC_COLUMNS[12:]]
        percentage = (
            100 * sum(counts) / n
            if n is not None and n > 0 and all(value is not None for value in counts)
            else None
        )
        result.append(f"<td>{_pct(percentage)}</td></tr>")
    summary = report.get("qc_summary") or {}
    result.append('<tr class="qc-sums" hidden aria-hidden="true">')
    for index, column in enumerate(QC_COLUMNS):
        key = column["key"]
        value = ""
        if index in _SUMMARY_COLUMNS:
            value = _date(summary.get(key)) if key == "packing_date" else _text(summary.get(key))
        elif key == "sample_count":
            value = _amount(totals["sample_count"])
        elif key == "pulp_temp":
            value = _amount(
                sum(_number(sample["qc_fields"].get(key)) or 0 for sample in report["samples"])
            )
        elif key in totals["counts"]:
            value = _amount(totals["counts"][key])
        result.append(f"<td>{value}</td>")
    result.append(
        f'<td>{_pct(totals["combined"])}</td></tr><tr class="qc-totals column-totals"><td colspan="8"></td><td colspan="4" class="total-label">Total Percent of each column</td>'
    )
    result.extend(
        f"<td>{_pct(totals['percentages'][column['key']])}</td>" for column in QC_COLUMNS[12:]
    )
    result.append(
        f'<td></td></tr><tr class="qc-totals combined-total"><td colspan="8"></td><td colspan="4" class="total-label">Total Percent Combined</td><td colspan="14">{_pct(totals["combined"])}</td><td colspan="3"></td></tr></tbody></table>'
    )
    result.append(_smartfruit(report, totals, confirmed))
    result.append("</main></body></html>")
    return "".join(result)
