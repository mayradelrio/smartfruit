"""QC workbook based on the business's existing ``Report`` worksheet.

The blank resource preserves the source layout with the AgroPeru company logo,
removing inspection values and personal workbook metadata. Recommendations are shown per sample;
the inspector's Level Flag and final decision remain separate.
"""

from __future__ import annotations

from copy import copy
from datetime import date, datetime
from importlib.resources import files
from io import BytesIO
from math import isfinite
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.styles.numbers import is_date_format
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties

from .evidence_display import evidence_caption, evidence_notice, evidence_photos
from .inspection import DEFECT_COLUMNS

# These names and their order come from the existing QC sheet and parser.
QC_FIELDS = (
    "label_brand",
    "pallet_id",
    "grower",
    "packing_date",
    "size",
    "avg_count_per_box",
    "plu_pct",
    "plu_coo",
    "sample_count",
    "open_rating",
    "color_rating",
    "pulp_temp",
    "decay",
    "styler",
    "mold",
    "soft",
    "skin_breakdown",
    "oleocellosis",
    "wounds",
    "int_dryness",
    "black_tips",
    "skin_defect",
    "scars",
    "white_stain",
    "blanching",
    "yellow_color",
    "stain",
    "undersize",
)

_VALID_DECISIONS = {"STANDARD", "EXPAND", "ESCALATE"}
_XML_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _write_value(cell, value):
    """Write inspection text literally, including leading spreadsheet operators."""
    cell.value = value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Some cells in the source template (notably PLU/Coo) carry a date
        # format despite holding ordinary identifiers. Do not turn a numeric
        # identifier from another QC source into a date on workbook reload.
        if is_date_format(cell.number_format):
            cell.number_format = "General"
    if isinstance(value, str):
        cell.data_type = "s"
        if value.lstrip().startswith(("=", "+", "-", "@")):
            cell.quotePrefix = True


def _write_date(cell, value):
    source_format = cell.number_format
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError:
            pass
    _write_value(cell, value)
    if isinstance(value, (date, datetime)):
        cell.number_format = source_format if is_date_format(source_format) else "mm-dd-yy"


def _number(value):
    # Excel SUM ignores strings, including a numeric string preserved from source.
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return value
    return None


def _snapshot_row(sheet, index):
    dimension = sheet.row_dimensions[index]
    return {
        "height": dimension.height,
        "hidden": dimension.hidden,
        "outlineLevel": dimension.outlineLevel,
        "collapsed": dimension.collapsed,
        "styles": [copy(sheet.cell(index, col)._style) for col in range(1, 30)],
    }


def _restore_row(sheet, index, snapshot):
    dimension = sheet.row_dimensions[index]
    for attribute in ("height", "hidden", "outlineLevel", "collapsed"):
        setattr(dimension, attribute, snapshot[attribute])
    for col, style in enumerate(snapshot["styles"], start=1):
        sheet.cell(index, col)._style = copy(style)


def _formula(sheet, address, text, cache, value):
    sheet[address] = text
    cache[address] = value


def _render_qc_table(sheet, samples, cache, summary):
    """Rebuild only the variable-length detail area using the original styles."""
    sample_rows = {index: _snapshot_row(sheet, index) for index in range(16, 24)}
    totals = _snapshot_row(sheet, 24)
    # The master 5878 hides its total row. The sanitized resource was unhidden
    # for inspection, so restore this source presentation when generating QC.
    totals["hidden"] = True
    percentages = _snapshot_row(sheet, 25)
    combined = _snapshot_row(sheet, 26)
    for merged in list(sheet.merged_cells.ranges):
        if merged.min_row >= 16:
            sheet.unmerge_cells(str(merged))
    sheet.delete_rows(16, max(1, sheet.max_row - 15))
    for index in list(sheet.row_dimensions):
        if index >= 16:
            del sheet.row_dimensions[index]

    for row, sample in enumerate(samples, start=16):
        fields = sample["qc_fields"]
        source_row = 23 if row == 15 + len(samples) else min(row, 22)
        _restore_row(sheet, row, sample_rows[source_row])
        for col, key in enumerate(QC_FIELDS, start=1):
            value = fields.get(key)
            if key == "packing_date":
                _write_date(sheet.cell(row, col), value)
            else:
                _write_value(sheet.cell(row, col), value)
        denominator = _number(fields.get("sample_count"))
        counts = [_number(fields.get(key)) for key in QC_FIELDS[12:]]
        complete = (
            denominator is not None
            and denominator > 0
            and all(count is not None for count in counts)
        )
        pct = sum(counts) / denominator if complete else None
        # An incomplete draft remains blank rather than looking like zero defects.
        _formula(
            sheet,
            f"AC{row}",
            f'=IF(AND(I{row}>0,COUNT(M{row}:AB{row})=16),SUM(M{row}:AB{row})/I{row},"")',
            cache,
            pct,
        )
        sheet[f"AC{row}"].number_format = "0.00%"

    end = 15 + len(samples)
    total_row = end + 1
    pct_row = end + 2
    combined_row = end + 3
    _restore_row(sheet, total_row, totals)
    _restore_row(sheet, pct_row, percentages)
    _restore_row(sheet, combined_row, combined)
    # These values are human summaries in the source QC total row. Preserve
    # them only when explicitly captured; do not derive ratings or identifiers.
    for column, key in {
        1: "label_brand",
        4: "packing_date",
        8: "plu_coo",
        10: "open_rating",
        11: "color_rating",
    }.items():
        if key == "packing_date":
            _write_date(sheet.cell(total_row, column), summary.get(key))
        else:
            _write_value(sheet.cell(total_row, column), summary.get(key))

    total_values = {}
    for col in (9, 12, *range(13, 29)):
        letter = get_column_letter(col)
        key = QC_FIELDS[col - 1]
        values = [_number(sample["qc_fields"].get(key)) for sample in samples]
        if col == 12:
            # The real QC uses SUM for Pulp, including files that store its
            # detail values as text. Excel ignores text rather than coercing it.
            value = sum(value for value in values if value is not None)
            total_values[col] = value
            _formula(sheet, f"{letter}{total_row}", f"=SUM({letter}16:{letter}{end})", cache, value)
            continue
        # Preserve the existing SUM conventions, but do not hide pending counts.
        complete = all(value is not None for value in values)
        value = sum(values) if complete else None
        total_values[col] = value
        _formula(
            sheet,
            f"{letter}{total_row}",
            f'=IF(COUNT({letter}16:{letter}{end})={len(samples)},SUM({letter}16:{letter}{end}),"")',
            cache,
            value,
        )
    denominator = total_values[9]
    complete = (
        denominator is not None
        and denominator > 0
        and all(total_values[col] is not None for col in range(13, 29))
    )
    combined_value = (
        sum(total_values[col] for col in range(13, 29)) / denominator if complete else None
    )
    _formula(
        sheet,
        f"AC{total_row}",
        f"=IF(AND(I{total_row}>0,COUNT(M{total_row}:AB{total_row})=16),"
        f'SUM(M{total_row}:AB{total_row})/I{total_row},"")',
        cache,
        combined_value,
    )
    sheet[f"AC{total_row}"].number_format = "0.00%"
    sheet.merge_cells(start_row=pct_row, start_column=9, end_row=pct_row, end_column=12)
    sheet.cell(pct_row, 9, "Total Percent of each column")
    for col in range(13, 29):
        letter = get_column_letter(col)
        value = total_values[col]
        percentage = (
            value / denominator
            if (value is not None and denominator is not None and denominator > 0)
            else None
        )
        _formula(
            sheet,
            f"{letter}{pct_row}",
            f"=IF(AND(ISNUMBER({letter}{total_row}),$I${total_row}>0),"
            f'{letter}{total_row}/$I${total_row},"")',
            cache,
            percentage,
        )
        sheet.cell(pct_row, col).number_format = "0.00%"
    sheet.merge_cells(
        start_row=combined_row,
        start_column=9,
        end_row=combined_row,
        end_column=12,
    )
    sheet.cell(combined_row, 9, "Total Percent Combined")
    sheet.merge_cells(
        start_row=combined_row,
        start_column=13,
        end_row=combined_row,
        end_column=26,
    )
    _formula(
        sheet,
        f"M{combined_row}",
        f'=IF(COUNT(M{pct_row}:AB{pct_row})=16,SUM(M{pct_row}:AB{pct_row}),"")',
        cache,
        combined_value,
    )
    sheet[f"M{combined_row}"].number_format = "0.00%"
    return combined_row + 3


def _line(sheet, row, label, value, *, height=27):
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
    sheet.merge_cells(start_row=row, start_column=9, end_row=row, end_column=29)
    _write_value(sheet.cell(row, 1), label)
    _write_value(sheet.cell(row, 9), value)
    border = Border(bottom=Side(style="hair", color="D5DFD8"))
    for col in range(1, 30):
        cell = sheet.cell(row, col)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        cell.font = Font(name="Calibri", size=11, bold=col == 1, color="24372E")
        cell.border = border
    sheet.row_dimensions[row].height = height
    return row + 1


def _banner(sheet, row, text, *, dark=False):
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=29)
    cell = sheet.cell(row, 1)
    _write_value(cell, text)
    cell.fill = PatternFill("solid", fgColor="166548" if dark else "E4F0E8")
    cell.font = Font(name="Calibri", size=13, bold=True, color="FFFFFF" if dark else "174B35")
    cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.row_dimensions[row].height = 30
    return row + 1


def _format_number(value, precision=4):
    number = _number(value)
    if number is None:
        return "pendiente"
    text = f"{number:.{precision}f}"
    return text.rstrip("0").rstrip(".") if precision else text


def _reception_value(value):
    """Keep the manifest's declared values; an unrecorded value is not zero."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "No registrado"
    return str(value)


def _reception_line(sheet, row, label, value):
    # Multiple manifest sizes are rendered as separate records. Preserve embedded
    # newlines as well, with enough row height for wrapped text and provenance.
    lines = sum(max(1, (len(part) + 179) // 180) for part in value.split("\n"))
    return _line(sheet, row, label, value, height=max(30, 15 * (lines + 1)))


def _render_reception(sheet, row, reception):
    row = _banner(sheet, row + 1, "Recepción · Checker y sistema actual")
    row = _reception_line(
        sheet, row, "Lectura escaneada", _reception_value(reception.get("scan_input"))
    )
    for index, record in enumerate(reception.get("records") or [], start=1):

        def value(key):
            return _reception_value(record.get(key))

        row = _reception_line(
            sheet,
            row,
            f"Registro de recepción {index}",
            f"Código de etiqueta: {value('scan_code')}; Alcance: {value('scan_level')}",
        )
        row = _reception_line(
            sheet,
            row,
            "Lote / pallet",
            f"AgroPeru Lot Number: {value('lot_id')}; N° PALLET: {value('pallet_id')}",
        )
        row = _reception_line(
            sheet,
            row,
            "Marca / tamaño declarado",
            f"Label: {value('label_brand')}; Size declared: {value('size_declared')}",
        )
        row = _reception_line(
            sheet, row, "Frutos DECLARADOS por caja", value("expected_count_per_box")
        )
        row = _reception_line(sheet, row, "Cajas recibidas", value("boxes_received"))
        row = _reception_line(sheet, row, "Peso recibido", value("qty_received_weight"))
        row = _reception_line(
            sheet,
            row,
            "País / envío",
            f"Country Of Origin: {value('country_origin')}; Envío: {value('shipment_id')}",
        )
        row = _reception_line(
            sheet,
            row,
            "Procedencia de recepción",
            f"Procedencia: {value('data_origin')}; Referencia: {value('source_record')}; "
            f"Estado: {value('status')}",
        )
    return row


def _review_action(value):
    return "EXTEND" if value == "EXPAND" else value


def _render_box_inspections(sheet, row, sample):
    boxes = sample.get("box_inspections") or []
    if not boxes:
        return row
    row = _banner(sheet, row + 1, "Inspección por caja · esperado y detectado")
    comparisons = {
        "matched": "Conteo detectado igual al declarado",
        "shortage": "Conteo detectado menor que el declarado",
        "excess": "Conteo detectado mayor que el declarado",
        "unavailable": "Sin conteo esperado disponible",
        "selection_required": "Pendiente de seleccionar la línea del manifiesto",
    }
    for box in boxes:
        row = _banner(sheet, row, f"Caja {box.get('sample_box_id') or 'Sin identificador'}")
        row = _line(
            sheet, row, "Estado de captura",
            "Finalizada" if box.get("status") == "completed" else "En captura",
        )
        row = _line(
            sheet, row, "Cobertura completa confirmada",
            "Sí" if box.get("coverage_confirmed") is True else "Pendiente",
        )
        for label, key in (
            ("Fotografías procesadas de la caja", "images_processed"),
            ("Frutos esperados por caja · manifiesto", "expected_count_per_box"),
            ("Frutos detectados en la caja", "actual_count"),
            ("Diferencia · detectados menos esperados", "count_difference"),
            ("Unidades menos detectadas", "missing_count"),
            ("Unidades más detectadas", "excess_count"),
        ):
            value = _number(box.get(key))
            row = _line(sheet, row, label, value if value is not None else "No disponible")
        deviation = _number(box.get("count_deviation_pct"))
        row = _line(
            sheet, row, "Desviación respecto al esperado",
            f"{deviation:.2f} %" if deviation is not None else "No disponible",
        )
        row = _line(
            sheet, row, "Comparación de conteo",
            comparisons.get(box.get("comparison_status"), "No disponible"),
        )
    return row


def _review_defect_text(fields):
    denominator = _number(fields.get("sample_count"))
    lines, observed = [], []
    for column in DEFECT_COLUMNS:
        if column["key"] == "oleocellosis":
            continue
        count = _number(fields.get(column["key"]))
        observed.append(count)
        if count is not None and count > 0:
            pct = 100 * count / denominator if denominator is not None and denominator > 0 else None
            lines.append(
                f"{column['label']}: {_format_number(count, 0)} frutos "
                f"({_format_number(pct)} %)"
            )
    if lines:
        return "\n".join(lines)
    return "Sin otros defectos registrados." if all(value == 0 for value in observed) else "Pendiente"


def _render_review_quantities(sheet, row, fields, vision, *, accumulated=False):
    denominator = _number(fields.get("sample_count"))
    affected = _number(fields.get("oleocellosis"))
    percentage = (
        100 * affected / denominator
        if affected is not None and denominator is not None and denominator > 0
        else None
    )
    row = _line(
        sheet, row,
        "Sample · frutos acumulados" if accumulated else "Sample · frutos de esta revisión",
        denominator,
    )
    row = _line(
        sheet, row, "Oleocellosis acumulada" if accumulated else "Oleocellosis · esta revisión",
        f"{_format_number(affected, 0)} frutos · {_format_number(percentage)} %",
    )
    defects = _review_defect_text(fields)
    row = _line(
        sheet, row, "Otros defectos acumulados" if accumulated else "Otros defectos · esta revisión", defects,
        height=min(409, max(30, 18 * (defects.count("\n") + 1))),
    )
    return _line(
        sheet, row, "Fotografías acumuladas" if accumulated else "Fotografías de esta revisión",
        vision.get("images_processed", len(vision.get("image_ids") or [])),
        height=38,
    )


def _render_review_history(sheet, row, sample):
    history = sample.get("review_history")
    if not history or not history.get("additional"):
        return row
    pallet = sample.get("pallet_id") or sample["qc_fields"].get("pallet_id")
    row = _banner(sheet, row + 1, f"Historial de revisiones · Paleta {pallet}")
    initial = history["initial"]
    row = _banner(sheet, row, "Revisión inicial · primera caja")
    row = _render_review_quantities(
        sheet, row, initial["qc_fields"], initial["inspection_summary"],
    )
    row = _line(
        sheet, row, "Sugerencia tras revisión inicial",
        _review_action(initial.get("system_recommendation")) or "Pendiente",
    )
    for review in history["additional"]:
        row = _banner(sheet, row + 1, f"Revisión adicional {review['review_number']} · caja adicional")
        row = _line(
            sheet, row, "Acción del inspector que amplió la inspección",
            _review_action(review.get("trigger_decision")) or "Pendiente",
        )
        row = _line(
            sheet, row, "Sugerencia antes de ampliar",
            _review_action(review.get("system_recommendation_before")) or "Pendiente",
        )
        row = _render_review_quantities(
            sheet, row, review["qc_fields"], review["inspection_summary"],
        )
        row = _line(sheet, row, "Observaciones de la revisión adicional", review.get("observations") or "")
        row = _line(
            sheet, row, "Sugerencia después de sumar la revisión",
            _review_action(review.get("system_recommendation_after")) or "Pendiente",
        )
    row = _banner(sheet, row + 1, f"Acumulado de la paleta {pallet} · todas las revisiones")
    return _render_review_quantities(
        sheet, row, sample["qc_fields"], sample.get("inspection_summary") or {}, accumulated=True,
    )


def _render_smartfruit(sheet, row, report, confirmed):
    status = "CONFIRMADO" if confirmed else "BORRADOR · pendiente de confirmación del inspector"
    row = _banner(sheet, row, f"SmartFruit · {status}", dark=True)
    row = _line(sheet, row, "Inspector", report.get("inspector_name") or "Pendiente")
    confirmed_at = report.get("confirmed_at")
    if confirmed and confirmed_at:
        instant = datetime.fromisoformat(confirmed_at.replace("Z", "+00:00"))
        confirmed_at = instant.astimezone(ZoneInfo("America/Lima")).strftime(
            "%d/%m/%Y %H:%M:%S (America/Lima)"
        )
    row = _line(
        sheet,
        row,
        "Confirmación del reporte",
        confirmed_at if confirmed else "Pendiente",
    )
    row = _line(sheet, row, "Observaciones", report.get("observations") or "")
    summary = report.get("lot_summary")
    if summary:
        row = _banner(sheet, row + 1, "Resumen del lote · cantidades registradas")
        row = _line(sheet, row, "Paletas inspeccionadas", summary["pallet_count"])
        row = _line(sheet, row, "Sample · frutos evaluados", summary["sample_count"])
        row = _line(sheet, row, "Incidencias de defectos", summary["total_defect_incidents"])
        row = _line(
            sheet,
            row,
            "Total Percent Combined",
            f"{_format_number(summary['total_combined_pct'])} %",
        )
        reason = summary.get("generated_reason", "")
        row = _line(
            sheet,
            row,
            "Resumen descriptivo propuesto de defectos",
            reason,
            height=min(409, max(38, 18 * (reason.count("\n") + 2))),
        )
    for sample in report["samples"]:
        sample_id = sample.get("sample_id") or "Sin identificador"
        pallet = sample.get("pallet_id") or sample["qc_fields"].get("pallet_id") or "Pendiente"
        row = _banner(sheet, row + 1, f"Muestra {sample_id} · N° PALLET {pallet}")
        severity = sample.get("business_severity", {})
        recommendation = sample.get("final_recommendation") or severity.get("recommendation")
        if sample.get("review_history") or sample.get("review_choice"):
            recommendation = _review_action(recommendation)
        row = _line(
            sheet,
            row,
            "Nivel / severidad resultante",
            f"{severity.get('business_max_level', 'Pendiente')} "
            f"· Quality: {severity.get('quality_max_level', 'Pendiente')} "
            f"· Condition: {severity.get('condition_max_level', 'Pendiente')}",
        )
        row = _line(sheet, row, "Recomendación SmartFruit", recommendation or "Pendiente")
        reasons = sample.get("recommendation_reasons", severity.get("reasons", []))
        row = _line(sheet, row, "Motivo", "; ".join(str(x) for x in reasons), height=38)
        predictive = sample.get("predictive") or {}
        enabled = predictive.get("enabled") is True
        row = _line(sheet, row, "Predictive", "ON - Experimental" if enabled else "OFF")
        if enabled:
            loss = predictive.get("predicted_loss_pct")
            display = f"{_format_number(loss)} %" if _number(loss) is not None else "No disponible"
            row = _line(sheet, row, "predicted_loss_pct", display)
        decision = sample.get("inspector_final_decision")
        sample_confirmed = (
            sample.get("inspector_confirmed") is True and decision in _VALID_DECISIONS
        )
        if not (confirmed and sample_confirmed) and sample.get("review_choice"):
            row = _line(
                sheet, row, "Estado inspector (pendiente de confirmación)",
                _review_action(sample["review_choice"]),
            )
        if sample.get("review_history") or sample.get("review_choice"):
            decision = _review_action(decision)
        decision_text = (
            decision
            if sample_confirmed
            else (f"{decision} (pendiente de confirmación)" if decision else "Pendiente")
        )
        row = _line(sheet, row, "Decisión final del inspector", decision_text)
        row = _line(
            sheet,
            row,
            "Confirmación del inspector",
            "Confirmada" if confirmed and sample_confirmed else "Pendiente",
        )
        row = _line(sheet, row, "Observaciones de la muestra", sample.get("observations") or "")
        row = _render_box_inspections(sheet, row, sample)
        row = _render_review_history(sheet, row, sample)
        vision = sample.get("inspection_summary") or {}
        row = _line(
            sheet,
            row,
            "Vision AI · Oleocellosis",
            f"Frutos evaluados: {_format_number(vision.get('total_fruits'), 0)}; "
            f"cantidad con oleocelosis: {_format_number(vision.get('oleocellosis_count'), 0)}; "
            f"porcentaje: {_format_number(vision.get('oleocellosis_pct'))} %; "
            f"confianza media: {_format_number(vision.get('mean_confidence'), 6)}",
            height=38,
        )
        row = _line(
            sheet,
            row,
            "Resumen de fotografías Vision",
            f"Fotografías procesadas: {vision.get('images_processed', len(vision.get('image_ids') or []))}; "
            f"duplicados ignorados: {len(vision.get('duplicate_image_ids_ignored') or [])}; "
            f"baja confianza: {vision.get('low_confidence_count', 0)} "
            f"(umbral {vision.get('low_confidence_threshold', 'no indicado')})",
            height=42,
        )
        coverage = sample.get("rule_coverage") or {}
        evaluated = ", ".join(str(x) for x in coverage.get("evaluated", []))
        excluded = ", ".join(str(x) for x in coverage.get("not_evaluated", []))
        row = _line(
            sheet,
            row,
            "Cobertura de reglas",
            f"Evaluados: {evaluated or 'no indicada'}. "
            f"Sin regla implementada: {excluded or 'no indicado'}. "
            "La recomendación corresponde a los defectos con regla y a esta muestra.",
            height=55,
        )
        row = _line(
            sheet,
            row,
            "Política de frontera",
            severity.get("boundary_policy", "No indicada"),
        )
        notice = evidence_notice(sample, len(evidence_photos(sample)))
        if notice:
            row = _line(sheet, row, "Evidencia fotográfica", notice, height=38)
        if sample.get("reception"):
            row = _render_reception(sheet, row, sample["reception"])
    return row


def _render_evidence_sheet(workbook, samples):
    entries = [
        (sample, photo, data)
        for sample in samples for photo, _, data in evidence_photos(sample)
    ]
    if not entries:
        return
    # Pillow is optional in the browser runtime. Existing reports without
    # attached photos must remain exportable without importing that dependency.
    from openpyxl.drawing.image import Image

    sheet = workbook.create_sheet("Evidencia")
    sheet.sheet_view.showGridLines = False
    for column in range(1, 9):
        sheet.column_dimensions[get_column_letter(column)].width = 12
    sheet.merge_cells("A1:H1")
    sheet["A1"] = "Evidencia fotográfica · oleocelosis detectada"
    sheet["A1"].font = Font(name="Calibri", size=15, bold=True, color="174B35")
    sheet.row_dimensions[1].height = 30
    row = 3
    for number, (sample, photo, data) in enumerate(entries, start=1):
        picture = Image(BytesIO(data))
        scale = min(640 / picture.width, 380 / picture.height, 1)
        picture.width = round(picture.width * scale)
        picture.height = round(picture.height * scale)
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        _write_value(sheet.cell(row, 1), evidence_caption(sample, photo, number))
        sheet.cell(row, 1).font = Font(name="Calibri", size=11, bold=True, color="24372E")
        sheet.cell(row, 1).alignment = Alignment(wrap_text=True, vertical="top")
        sheet.row_dimensions[row].height = 32
        sheet.add_image(picture, f"A{row + 1}")
        image_rows = max(1, (picture.height + 19) // 20)
        for image_row in range(row + 1, row + image_rows + 1):
            sheet.row_dimensions[image_row].height = 15
        row += image_rows + 3
    sheet.print_area = f"A1:H{row}"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = "1:1"
    sheet.oddFooter.right.text = "Página &P de &N"


def _cache_formulas(workbook_bytes, cache):
    """Retain formulas and supply their computed values for non-Excel readers."""
    source = BytesIO(workbook_bytes)
    output = BytesIO()
    ns = {"s": _XML_NS}
    with ZipFile(source) as archive, ZipFile(output, "w") as target:
        for member in archive.infolist():
            data = archive.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                document = ET.fromstring(data)
                for cell in document.findall(".//s:sheetData/s:row/s:c", ns):
                    address = cell.attrib.get("r")
                    if address not in cache or cell.find("s:f", ns) is None:
                        continue
                    value = cell.find("s:v", ns)
                    if value is None:
                        value = ET.SubElement(cell, f"{{{_XML_NS}}}v")
                    number = cache[address]
                    if number is None:
                        cell.attrib["t"] = "str"
                        value.text = None
                    else:
                        cell.attrib.pop("t", None)
                        value.text = str(number)
                data = ET.tostring(document, encoding="utf-8", xml_declaration=True)
            target.writestr(member, data)
    return output.getvalue()


def export_qc_xlsx(report: dict) -> bytes:
    """Generate the current QC format plus SmartFruit, without changing source files.

    The report wrapper and samples are the application contract documented by the
    caller. An unconfirmed report is exportable only as an explicit draft. This
    renderer does not infer a lot recommendation from individual sample results.
    """
    if not isinstance(report, dict) or not isinstance(report.get("samples"), list):
        raise ValueError("El reporte debe contener una lista de muestras.")
    samples = report["samples"]
    if not samples:
        raise ValueError("El QC Report necesita al menos una muestra.")
    if any(
        not isinstance(sample, dict) or not isinstance(sample.get("qc_fields"), dict)
        for sample in samples
    ):
        raise ValueError("Cada muestra debe contener sus campos QC.")
    resource = files("smartfruit").joinpath("resources/qc_template.xlsx")
    workbook = openpyxl.load_workbook(BytesIO(resource.read_bytes()))
    sheet = workbook["Report"]
    header = report.get("qc_header") or {}
    for cell, key in {
        "L4": "vessel",
        "L6": "container",
        "L8": "lot_id",
        "L10": "country_origin",
        "Q3": "remarks",
        "AB3": "grade",
        "AB6": "color",
        "AB9": "plu_pct",
    }.items():
        value = header.get(key)
        if key == "lot_id" and value is None:
            value = report.get("lot_id")
        _write_value(sheet[cell], value)
    _write_date(sheet["L2"], header.get("inspection_date"))
    flag = header.get("Level_Flag")
    _write_value(sheet["U2"], f"Level Flag: {flag}" if flag is not None else "Level Flag:")
    reason = header.get("reason")
    _write_value(sheet["X2"], f"Reason:{reason}" if reason else "Reason:")
    confirmed = (
        report.get("inspector_confirmed") is True
        and bool(report.get("inspector_name"))
        and bool(report.get("confirmed_at"))
        and all(
            sample.get("inspector_confirmed") is True
            and sample.get("inspector_final_decision") in _VALID_DECISIONS
            for sample in samples
        )
    )
    cache = {}
    summary = report.get("qc_summary") or {}
    if not isinstance(summary, dict):
        raise ValueError("El resumen QC debe contener los campos del renglón de totales.")
    row = _render_qc_table(sheet, samples, cache, summary)
    final_row = _render_smartfruit(sheet, row, report, confirmed)
    _render_evidence_sheet(workbook, samples)
    sheet.freeze_panes = "J16"
    sheet.sheet_view.showGridLines = False
    sheet.print_title_rows = "14:15"
    sheet.print_area = f"A1:AC{final_row}"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.oddHeader.center.text = "SmartFruit · " + ("CONFIRMADO" if confirmed else "BORRADOR")
    sheet.oddFooter.right.text = "Página &P de &N"
    workbook.calculation = CalcProperties(
        calcId=191029,
        fullCalcOnLoad=True,
        forceFullCalc=True,
        calcMode="auto",
    )
    destination = BytesIO()
    workbook.save(destination)
    return _cache_formulas(destination.getvalue(), cache)
