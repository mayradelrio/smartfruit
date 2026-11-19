"""Expected box counts stay separate from the accumulated pallet QC row."""

from copy import deepcopy
from html.parser import HTMLParser
from io import BytesIO

import openpyxl
import pytest

from smartfruit.print_report import render_qc_print
from smartfruit.qc_report import QC_FIELDS, export_qc_xlsx


def box(box_id, actual, expected):
    difference = actual - expected if expected is not None else None
    return {
        "sample_box_id": box_id,
        "status": "completed",
        "coverage_confirmed": True,
        "manifest_record_index": None,
        "images_processed": 13,
        "actual_count": actual,
        "expected_count_per_box": expected,
        "count_difference": difference,
        "count_deviation_pct": 100 * difference / expected if expected else None,
        "missing_count": max(-difference, 0) if difference is not None else None,
        "excess_count": max(difference, 0) if difference is not None else None,
        "oleocellosis_count": 0,
        "oleocellosis_pct": 0,
        "comparison_status": (
            "unavailable" if difference is None else
            "shortage" if difference < 0 else "excess" if difference > 0 else "matched"
        ),
    }


@pytest.fixture
def report():
    fields = dict.fromkeys(QC_FIELDS, "")
    fields.update(dict.fromkeys(QC_FIELDS[12:], 0))
    fields.update(pallet_id="P1", sample_count=298, avg_count_per_box=142)
    return {
        "qc_header": {"lot_id": "L1", "inspection_date": "2026-11-15"},
        "samples": [{
            "sample_id": "S1",
            "pallet_id": "P1",
            "qc_fields": fields,
            "inspection_summary": {"total_fruits": 298, "oleocellosis_count": 0},
            "box_inspections": [box("BOX_001", 146, 150), box("BOX_002", 152, 150)],
        }],
    }


def sheet(report):
    return openpyxl.load_workbook(BytesIO(export_qc_xlsx(report)), data_only=True)["Report"]


def values(sheet, label):
    return [
        sheet.cell(row, 9).value for row in range(1, sheet.max_row + 1)
        if sheet.cell(row, 1).value == label
    ]


class QCRowCounter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = 0

    def handle_starttag(self, tag, attrs):
        if tag == "tr" and ("class", "qc-data") in attrs:
            self.rows += 1


def test_reports_compare_each_box_without_comparing_the_pallet_total(report):
    original = deepcopy(report)
    workbook = sheet(report)
    html = render_qc_print(report)
    assert workbook["I16"].value == 298 and workbook["F16"].value == 142
    assert workbook["B16"].value == "P1" and workbook["B17"].value != "P1"
    assert values(workbook, "Frutos esperados por caja · manifiesto") == [150, 150]
    assert values(workbook, "Frutos detectados en la caja") == [146, 152]
    assert values(workbook, "Diferencia · detectados menos esperados") == [-4, 2]
    assert values(workbook, "Unidades menos detectadas") == [4, 0]
    assert values(workbook, "Unidades más detectadas") == [0, 2]
    assert values(workbook, "Desviación respecto al esperado") == ["-2.67 %", "1.33 %"]
    assert "Caja BOX_001" in html and "Caja BOX_002" in html
    assert "Unidades menos detectadas</dt><dd>4" in html
    assert "Diferencia · detectados menos esperados</dt><dd>-4" in html
    assert "Desviación respecto al esperado</dt><dd>-2.67%" in html
    assert "Desviación respecto al esperado</dt><dd>1.33%" in html
    parser = QCRowCounter()
    parser.feed(html)
    assert parser.rows == 1
    assert report == original


def test_unknown_expected_count_stays_unavailable_in_both_exports(report):
    report["samples"][0]["box_inspections"] = [box("BOX_001", 146, None)]
    workbook = sheet(report)
    html = render_qc_print(report)
    for label in (
        "Frutos esperados por caja · manifiesto", "Diferencia · detectados menos esperados",
        "Desviación respecto al esperado", "Unidades menos detectadas", "Unidades más detectadas",
    ):
        assert values(workbook, label) == ["No disponible"]
        assert f"{label}</dt><dd>No disponible" in html
    assert values(workbook, "Comparación de conteo") == ["Sin conteo esperado disponible"]
    assert "Sin conteo esperado disponible" in html
    assert values(workbook, "Frutos detectados en la caja") == [146]


def test_box_identifiers_remain_literal_in_excel_and_escaped_in_print(report):
    identifier = '=HYPERLINK("https://example.invalid","<script>box</script>")'
    report["samples"][0]["box_inspections"][0]["sample_box_id"] = identifier
    workbook = sheet(report)
    matching = [cell for row in workbook for cell in row if cell.value == f"Caja {identifier}"]
    assert len(matching) == 1 and matching[0].data_type == "s"
    html = render_qc_print(report)
    assert "<script>box</script>" not in html
    assert "&lt;script&gt;box&lt;/script&gt;" in html


def test_legacy_reports_do_not_acquire_inferred_box_comparisons(report):
    sample = report["samples"][0]
    sample.pop("box_inspections")
    original_html = render_qc_print(report)
    assert "Inspección por caja · esperado y detectado" not in original_html
    assert values(sheet(report), "Frutos esperados por caja · manifiesto") == []
    sample["box_inspections"] = []
    assert render_qc_print(report) == original_html
