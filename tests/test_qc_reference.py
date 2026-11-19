"""Fidelity to the real QC layout, with private values kept out of version control.

The private checks reconstruct QC fields directly from the source spreadsheets.
They test the renderer, not Vision inference or Business Severity. Always-run
checks use a metadata-only reference and entirely synthetic inspection values.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from copy import copy, deepcopy
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
import pytest
from PIL import Image

from smartfruit.print_report import render_qc_print
from smartfruit.qc_report import QC_FIELDS, export_qc_xlsx

ROOT = Path(__file__).resolve().parents[1]
BRAND_LOGO = ROOT / "src/smartfruit/resources/branding/agroperu-logo.png"
REFERENCE = json.loads(
    (ROOT / "tests/fixtures/qc_layout_reference.json").read_text(encoding="utf-8")
)
SUMMARY_COLUMNS = {
    1: "label_brand",
    4: "packing_date",
    8: "plu_coo",
    10: "open_rating",
    11: "color_rating",
}


def _style_fingerprint(cell):
    style = {
        name: ET.tostring(copy(getattr(cell, name)).to_tree(), encoding="unicode")
        for name in ("font", "fill", "border", "alignment", "protection")
    }
    style.update(number_format=cell.number_format, quote_prefix=cell.quotePrefix)
    return hashlib.sha256(json.dumps(style, sort_keys=True).encode()).hexdigest()


def _logo_metadata(image):
    anchor = image.anchor
    result = {
        "width": image.width,
        "height": image.height,
        "anchor_type": type(anchor).__name__,
    }
    for key in ("_from", "to"):
        marker = getattr(anchor, key, None)
        if marker is not None:
            result[key] = {
                attr: getattr(marker, attr) for attr in ("col", "colOff", "row", "rowOff")
            }
    with Image.open(BytesIO(image._data())) as raster:
        result["rgba_pixel_sha256"] = hashlib.sha256(raster.convert("RGBA").tobytes()).hexdigest()
    return result


def _load(data, *, values=False):
    return openpyxl.load_workbook(BytesIO(data), data_only=values)["Report"]


def _synthetic_report(count=8):
    samples = []
    for index in range(count):
        fields = dict.fromkeys(QC_FIELDS, "N/A")
        fields.update(
            {
                "label_brand": "DEMO",
                "pallet_id": f"PALLET_DEMO_{index}",
                "packing_date": "N/A",
                "size": "42",
                "avg_count_per_box": 42,
                "plu_pct": "70",
                "plu_coo": "DEMO",
                "sample_count": 12,
                "open_rating": "DEMO",
                "color_rating": "DEMO",
                "pulp_temp": "50.0",
            }
        )
        fields.update(dict.fromkeys(QC_FIELDS[12:], 0))
        samples.append(
            {
                "sample_id": f"SAMPLE_DEMO_{index}",
                "pallet_id": fields["pallet_id"],
                "qc_fields": fields,
                "inspection_summary": {},
                "business_severity": {},
                "predictive": {"enabled": False},
                "inspector_confirmed": False,
            }
        )
    return {
        "schema_version": "1.1",
        "lot_id": "LOT_DEMO",
        "samples": samples,
        "qc_header": {
            "lot_id": "LOT_DEMO",
            "inspection_date": "2026-11-13",
            "vessel": "N/A",
            "container": "N/A",
            "country_origin": "DEMO",
            "remarks": "Fixture sintético de QC; no es inferencia Vision.",
            "Level_Flag": "",
            "reason": "",
            "grade": "DEMO",
            "color": "DEMO",
            "plu_pct": "70%",
        },
        "inspector_confirmed": False,
        "observations": "Validación de renderer; no evaluar modelos ni asociar fotografías.",
    }


def _find_cell(sheet, predicate):
    return next(cell for row in sheet for cell in row if predicate(cell.value))


def _private_source(filename):
    path = ROOT / "data/local/originals/qc" / filename
    if not path.exists():
        pytest.skip(f"Fuente QC privada no disponible localmente: {filename}")
    return path


def _report_from_qc_source(path):
    """Direct QC fixture only: intentionally do not manufacture Vision predictions."""
    sheet = openpyxl.load_workbook(path)["Report"]
    header_row = _find_cell(sheet, lambda value: value == "Label").row
    rows = [
        row
        for row in range(header_row + 1, sheet.max_row + 1)
        if sheet.cell(row, 2).value is not None
        and isinstance(sheet.cell(row, 9).value, (int, float))
    ]
    total_row = rows[-1] + 1
    # The lot value stays in this cell even when source branding differs.
    header = {"lot_id": sheet["L8"].value}
    for label, key in (
        ("Inspection Date:", "inspection_date"),
        ("Vessel:", "vessel"),
        ("Container:", "container"),
        ("Country Of Origin:", "country_origin"),
    ):
        label_cell = _find_cell(sheet, lambda value, label=label: value == label)
        header[key] = sheet.cell(label_cell.row, 12).value
    for prefix, key in (("Level Flag:", "Level_Flag"), ("Reason:", "reason")):
        cell = _find_cell(
            sheet, lambda value, prefix=prefix: isinstance(value, str) and value.startswith(prefix)
        )
        raw = cell.value.split(":", 1)[1]
        header[key] = raw.strip() if key == "Level_Flag" else raw
    remarks = _find_cell(sheet, lambda value: value == "Remarks:")
    header["remarks"] = sheet.cell(remarks.row + 1, 17).value
    for label, key in (("Grade:", "grade"), ("Color:", "color"), ("PLU%:", "plu_pct")):
        cell = _find_cell(sheet, lambda value, label=label: str(value or "").strip() == label)
        header[key] = sheet.cell(cell.row + 1, 28).value
    samples = []
    for index, row in enumerate(rows):
        fields = {key: sheet.cell(row, column).value for column, key in enumerate(QC_FIELDS, 1)}
        samples.append(
            {
                "sample_id": f"QC_REFERENCE_{index + 1}",
                "pallet_id": fields["pallet_id"],
                "qc_fields": fields,
                # Empty means not evaluated; historical QC values are not Vision output.
                "inspection_summary": {},
                "business_severity": {},
                "predictive": {"enabled": False},
                "inspector_confirmed": False,
            }
        )
    summary = {
        key: sheet.cell(total_row, column).value
        for column, key in SUMMARY_COLUMNS.items()
        if sheet.cell(total_row, column).value is not None
    }
    return (
        {
            "schema_version": "1.1",
            "lot_id": header["lot_id"],
            "qc_header": header,
            "qc_summary": summary,
            "samples": samples,
            "inspector_confirmed": False,
            "observations": "Fixture de QC histórico para renderer; no es inferencia Vision.",
        },
        sheet,
        rows,
    )


def test_master_layout_against_reference_without_private_data():
    sheet = _load(export_qc_xlsx(_synthetic_report()))
    assert sheet.title == "Report"
    for address, label in REFERENCE["labels"].items():
        assert sheet[address].value == label, address
    assert (
        sorted(str(merged) for merged in sheet.merged_cells.ranges if merged.max_row <= 26)
        == (REFERENCE["core_merges"])
    )
    for key, expected in REFERENCE["column_dimensions"].items():
        actual = sheet.column_dimensions[key]
        assert {name: getattr(actual, name) for name in expected} == expected, key
    for row, height in REFERENCE["row_heights"].items():
        assert sheet.row_dimensions[int(row)].height == height, row
    for address, fingerprint in REFERENCE["style_sha256"].items():
        assert _style_fingerprint(sheet[address]) == fingerprint, address
    assert [_logo_metadata(image) for image in sheet._images] == REFERENCE["logos"]
    assert [row for row in range(1, 27) if sheet.row_dimensions[row].hidden] == (
        REFERENCE["source_hidden_rows"]
    )
    assert sheet["A29"].value.startswith("SmartFruit · BORRADOR")


@pytest.mark.parametrize("relative", [
    "src/smartfruit/resources/qc_template.xlsx", "templates/qc/smartfruit_qc_blank.xlsx",
])
def test_clean_templates_use_agroperu_logo_with_preserved_qc_geometry(relative):
    with ZipFile(ROOT / relative) as archive:
        media = [name for name in archive.namelist() if name.startswith("xl/media/")]
        assert media == ["xl/media/image1.png"]
        assert archive.read(media[0]) == BRAND_LOGO.read_bytes()
        drawing = ET.fromstring(archive.read("xl/drawings/drawing1.xml"))
        ns = {"d": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"}
        properties = drawing.find(".//d:cNvPr", ns)
        assert properties.attrib["descr"] == "Logo de AgroPeru"
        extent = drawing.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}ext")
        assert int(extent.attrib["cy"]) == 1314426
        assert int(extent.attrib["cx"]) <= 6016300
        with Image.open(BRAND_LOGO) as raster:
            assert math.isclose(
                int(extent.attrib["cx"]) / int(extent.attrib["cy"]),
                raster.width / raster.height, abs_tol=1e-6,
            )
    sheet = openpyxl.load_workbook(ROOT / relative)["Report"]
    assert [_logo_metadata(image) for image in sheet._images] == REFERENCE["logos"]
    assert sheet["J8"].value == "AgroPeru Lot Number:"


def test_export_and_self_contained_print_inherit_agroperu_branding():
    report = _synthetic_report(count=1)
    logo = BRAND_LOGO.read_bytes()
    with Image.open(BytesIO(logo)) as raster:
        assert raster.format == "PNG" and raster.mode == "RGBA"
        assert raster.getchannel("A").getextrema()[0] == 0
    with ZipFile(BytesIO(export_qc_xlsx(report))) as archive:
        assert archive.read("xl/media/image1.png") == logo
    html = render_qc_print(report)
    embedded = re.search(r'<img class="logo" src="data:image/png;base64,([^\"]+)"', html)
    assert embedded is not None
    assert base64.b64decode(embedded.group(1), validate=True) == logo


def test_summary_is_optional_literal_and_never_inferred():
    report = _synthetic_report(count=1)
    absent = _load(export_qc_xlsx(report))
    assert absent.row_dimensions[17].hidden is True
    for column in SUMMARY_COLUMNS:
        assert absent.cell(17, column).value is None
    report["qc_summary"] = {
        "label_brand": "=1+1",
        "packing_date": "2026-11-13",
        "plu_coo": 4048,
        "open_rating": "QC MANUAL",
        "color_rating": "QC MANUAL",
    }
    before = deepcopy(report)
    sheet = _load(export_qc_xlsx(report))
    assert report == before
    assert sheet["A17"].value == "=1+1" and sheet["A17"].data_type == "s"
    assert sheet["D17"].value == datetime(2026, 11, 13)
    assert sheet["H17"].value == 4048
    assert sheet["J17"].value == "QC MANUAL"
    assert sheet["K17"].value == "QC MANUAL"


def test_numeric_plu_identifier_is_not_reinterpreted_as_date():
    report = _synthetic_report(count=1)
    report["samples"][0]["qc_fields"]["plu_coo"] = 4048
    sheet = _load(export_qc_xlsx(report))
    assert sheet["H16"].value == 4048
    assert sheet["H16"].number_format == "General"


def test_pulp_total_follows_original_excel_sum_without_text_coercion():
    report = _synthetic_report(count=3)
    report["samples"][0]["qc_fields"]["pulp_temp"] = "50.0"
    report["samples"][1]["qc_fields"]["pulp_temp"] = 51.5
    report["samples"][2]["qc_fields"]["pulp_temp"] = ""
    data = export_qc_xlsx(report)
    assert _load(data)["L19"].value == "=SUM(L16:L18)"
    assert _load(data, values=True)["L19"].value == 51.5


@pytest.mark.parametrize("filename", ["5878.xlsx", "5874.xlsx", "5824.xlsx"])
def test_private_qc_columns_values_summaries_and_formula_results(filename):
    source = _private_source(filename)
    original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    report, original, source_rows = _report_from_qc_source(source)
    data = export_qc_xlsx(report)
    rendered = _load(data)
    values = _load(data, values=True)
    source_values = openpyxl.load_workbook(source, data_only=True)["Report"]
    source_header = source_rows[0] - 1
    assert [original.cell(source_header, col).value for col in range(1, 30)] == [
        rendered.cell(15, col).value for col in range(1, 30)
    ]
    for output_row, source_row in enumerate(source_rows, 16):
        for column in range(1, 29):
            assert (
                rendered.cell(output_row, column).value == original.cell(source_row, column).value
            )
        original_formula = original.cell(source_row, 29).value
        assert f"SUM(M{source_row}:AB{source_row})" in original_formula
        assert f"SUM(M{output_row}:AB{output_row})" in rendered.cell(output_row, 29).value
        denominator = original.cell(source_row, 9).value
        expected = sum(original.cell(source_row, column).value for column in range(13, 29))
        expected /= denominator
        assert math.isclose(values.cell(output_row, 29).value, expected, abs_tol=1e-12)
        cached = source_values.cell(source_row, 29).value
        if cached is not None:
            assert math.isclose(values.cell(output_row, 29).value, cached, abs_tol=1e-12)
    total_row = 16 + len(source_rows)
    source_total = source_rows[-1] + 1
    for column, key in SUMMARY_COLUMNS.items():
        assert rendered.cell(total_row, column).value == report["qc_summary"].get(key)
    assert rendered.row_dimensions[total_row].hidden is True
    total_count = sum(original.cell(row, 9).value for row in source_rows)
    assert values.cell(total_row, 9).value == total_count
    expected_pulp = sum(
        original.cell(row, 12).value
        for row in source_rows
        if isinstance(original.cell(row, 12).value, (int, float))
    )
    assert values.cell(total_row, 12).value == expected_pulp
    cached_pulp = source_values.cell(source_total, 12).value
    if cached_pulp is not None:
        assert values.cell(total_row, 12).value == cached_pulp
    combined = 0
    for column in range(13, 29):
        expected = sum(original.cell(row, column).value for row in source_rows)
        assert values.cell(total_row, column).value == expected
        assert math.isclose(values.cell(total_row + 1, column).value, expected / total_count)
        cached = source_values.cell(source_total + 1, column).value
        if cached is not None:
            assert math.isclose(values.cell(total_row + 1, column).value, cached, abs_tol=1e-12)
        combined += expected / total_count
    assert math.isclose(values.cell(total_row + 2, 13).value, combined, abs_tol=1e-12)
    assert math.isclose(values.cell(total_row, 29).value, combined, abs_tol=1e-12)
    cached_combined = source_values.cell(source_total + 2, 13).value
    if cached_combined is not None:
        assert math.isclose(combined, cached_combined, abs_tol=1e-12)
    assert rendered.cell(total_row + 5, 1).value.startswith("SmartFruit · BORRADOR")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_sha


def test_private_master_header_values_and_style_match():
    source = _private_source("5878.xlsx")
    report, original, rows = _report_from_qc_source(source)
    rendered = _load(export_qc_xlsx(report))
    for address in (
        "L2",
        "L4",
        "L6",
        "L8",
        "L10",
        "Q3",
        "U2",
        "X2",
        "AB3",
        "AB6",
        "AB9",
    ):
        assert rendered[address].value == original[address].value, address
    for row in range(1, rows[-1] + 4):
        for column in range(1, 30):
            address = original.cell(row, column).coordinate
            assert _style_fingerprint(rendered[address]) == _style_fingerprint(original[address]), (
                address
            )
        assert rendered.row_dimensions[row].height == original.row_dimensions[row].height
        assert rendered.row_dimensions[row].hidden == original.row_dimensions[row].hidden
        assert (
            rendered.row_dimensions[row].outlineLevel == original.row_dimensions[row].outlineLevel
        )
        assert rendered.row_dimensions[row].collapsed == original.row_dimensions[row].collapsed
    # AgroPeru keeps the original top-left and height. Its shorter right edge
    # fits the new aspect ratio inside the historical logo area.
    rendered_logo = _logo_metadata(rendered._images[0])
    historical_logo = _logo_metadata(original._images[0])
    for key in ("anchor_type", "_from"):
        assert rendered_logo[key] == historical_logo[key]
    for key in ("row", "rowOff"):
        assert rendered_logo["to"][key] == historical_logo["to"][key]
    assert rendered_logo["to"]["col"] <= historical_logo["to"]["col"]
    assert rendered_logo == REFERENCE["logos"][0]
