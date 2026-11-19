"""Additional-box history stays separate while the QC row contains pallet totals."""

from copy import deepcopy
from html.parser import HTMLParser
from io import BytesIO

import openpyxl
import pytest
from review_helpers import confirm_vision_records

from smartfruit.inspection import MANUAL_DEFECTS
from smartfruit.lot_summary import build_lot_summary
from smartfruit.print_report import render_qc_print
from smartfruit.qc_report import QC_FIELDS, export_qc_xlsx
from smartfruit.vision import aggregate_vision_sample
from smartfruit.workflow import evaluate_inspection


def vision(image_id, total, affected):
    return {
        "image_id": image_id, "partition": "test", "total_fruits": total,
        "oleocellosis_count": affected, "oleocellosis_pct": 100 * affected / total,
        "mean_confidence": 0.95,
        "fruit_predictions": [
            {
                "crop_id": f"CROP-{index}",
                "predicted_class": "con_oleocelosis" if index < affected else "sin_oleocelosis",
                "oleocellosis_probability": 0.95 if index < affected else 0.05,
                "confidence": 0.95,
            }
            for index in range(total)
        ],
    }


def fields(total, affected, scars):
    result = dict.fromkeys(QC_FIELDS, "")
    result.update({column["key"]: 0 for column in MANUAL_DEFECTS})
    result.update(
        pallet_id="PALLET-TEST", label_brand="TEST-LABEL", sample_count=total,
        oleocellosis=affected, scars=scars,
    )
    return result


@pytest.fixture
def report():
    initial_vision = confirm_vision_records([vision("INITIAL-BOX", 12, 1)])[0]
    extra_vision = confirm_vision_records([vision("EXTRA-BOX", 24, 6)])[0]
    initial_fields = fields(12, 1, 2)
    extra_fields = fields(24, 6, 1)
    payload = {
        "qc_header": {"lot_id": "LOT-TEST", "inspection_date": "2026-11-15", "Level_Flag": 2},
        "samples": [{
            "sample_id": "SAMPLE-TEST", "pallet_id": "PALLET-TEST",
            "vision_records": [initial_vision, extra_vision], "vision_covers_sample": True,
            "qc_fields": fields(36, 7, 3),
        }],
    }
    result = evaluate_inspection(payload)
    def summary(records):
        return aggregate_vision_sample(
            records, "SAMPLE-TEST", "LOT-TEST", "PALLET-TEST"
        )["vision_summary"]
    result["samples"][0]["review_choice"] = "EXPAND"
    result["samples"][0]["review_history"] = {
        "initial": {
            "vision_records": [initial_vision], "qc_fields": initial_fields,
            "inspection_summary": summary([initial_vision]), "system_recommendation": "EXPAND",
        },
        "additional": [{
            "review_number": 2, "trigger_decision": "EXPAND", "vision_records": [extra_vision],
            "manual_defects": {column["key"]: extra_fields[column["key"]] for column in MANUAL_DEFECTS},
            "qc_fields": extra_fields, "inspection_summary": summary([extra_vision]),
            "observations": "Second box inspected separately.",
            "system_recommendation_before": "EXPAND", "system_recommendation_after": "ESCALATE",
        }],
    }
    return result


def label_values(sheet, label):
    return [
        sheet.cell(row, 9).value for row in range(1, sheet.max_row + 1)
        if sheet.cell(row, 1).value == label
    ]


def test_excel_keeps_one_accumulated_qc_row_and_separate_additional_box_detail(report):
    original = deepcopy(report)
    sheet = openpyxl.load_workbook(BytesIO(export_qc_xlsx(report)), data_only=True)["Report"]
    assert sheet["B16"].value == "PALLET-TEST" and sheet["B17"].value != "PALLET-TEST"
    assert sheet["I16"].value == 36 and sheet["R16"].value == 7 and sheet["W16"].value == 3
    assert sheet["AC16"].value == pytest.approx(10 / 36)
    assert label_values(sheet, "Sample · frutos de esta revisión") == [12, 24]
    assert label_values(sheet, "Sample · frutos acumulados") == [36]
    assert label_values(sheet, "Oleocellosis acumulada") == ["7 frutos · 19.4444 %"]
    assert label_values(sheet, "Acción del inspector que amplió la inspección") == ["EXTEND"]
    assert label_values(sheet, "Sugerencia antes de ampliar") == ["EXTEND"]
    assert label_values(sheet, "Sugerencia después de sumar la revisión") == ["ESCALATE"]
    assert label_values(sheet, "Observaciones de la revisión adicional") == ["Second box inspected separately."]
    assert label_values(sheet, "Otros defectos acumulados") == ["Scars: 3 frutos (8.3333 %)"]
    assert label_values(sheet, "Fotografías acumuladas") == [2]
    assert label_values(sheet, "Fotografías de esta revisión") == [1, 1]
    assert label_values(sheet, "Estado inspector (pendiente de confirmación)") == ["EXTEND"]
    assert report == original


def test_print_exposes_initial_extra_and_weighted_total_without_duplicate_pallet_rows(report):
    original = deepcopy(report)
    html = render_qc_print(report)

    class Parser(HTMLParser):
        rows = 0

        def handle_starttag(self, tag, attrs):
            if tag == "tr" and ("class", "qc-data") in attrs:
                self.rows += 1

    parsed = Parser()
    parsed.feed(html)
    assert parsed.rows == 1
    assert "Revisión inicial · primera caja" in html
    assert "Revisión adicional 2 · caja adicional" in html
    assert "Acumulado de la paleta PALLET-TEST" in html
    assert "Oleocellosis acumulada</dt><dd>7 frutos · 19.44%" in html
    assert "Sample · frutos de esta revisión</dt><dd>12" in html
    assert "Sample · frutos de esta revisión</dt><dd>24" in html
    assert "Sample · frutos acumulados</dt><dd>36" in html
    assert "Estado inspector (pendiente de confirmación)</dt><dd>EXTEND" in html
    assert "Fotografías acumuladas</dt><dd>2" in html
    assert "INITIAL-BOX" in html and "EXTRA-BOX" in html  # Auditable Vision source IDs.
    assert report == original


def test_history_text_remains_literal_in_excel_and_escaped_in_print(report):
    extra = report["samples"][0]["review_history"]["additional"][0]
    extra["observations"] = '=HYPERLINK("https://example.invalid","box")'
    sheet = openpyxl.load_workbook(BytesIO(export_qc_xlsx(report)))["Report"]
    rows = [row for row in range(1, sheet.max_row + 1)
            if sheet.cell(row, 1).value == "Observaciones de la revisión adicional"]
    cell = sheet.cell(rows[0], 9)
    assert cell.value == extra["observations"] and cell.data_type == "s" and cell.quotePrefix
    extra["observations"] = '<img src=x onerror="alert(1)">'
    html = render_qc_print(report)
    assert '<img src=x onerror="alert(1)">' not in html
    assert "&lt;img src=x onerror=&quot;" in html


def test_several_additional_boxes_keep_their_individual_counts(report):
    sample = report["samples"][0]
    history = sample["review_history"]
    third_vision = vision("THIRD-BOX", 6, 0)
    third_fields = fields(6, 0, 0)
    third_summary = aggregate_vision_sample(
        [third_vision], "SAMPLE-TEST", "LOT-TEST", "PALLET-TEST"
    )["vision_summary"]
    history["additional"].append({
        "review_number": 3, "trigger_decision": "EXPAND", "vision_records": [third_vision],
        "manual_defects": {column["key"]: 0 for column in MANUAL_DEFECTS},
        "qc_fields": third_fields, "inspection_summary": third_summary,
        "observations": "Third box.", "system_recommendation_before": "ESCALATE",
        "system_recommendation_after": "ESCALATE",
    })
    sample["qc_fields"] = fields(42, 7, 3)
    records = history["initial"]["vision_records"] + [
        record for review in history["additional"] for record in review["vision_records"]
    ]
    sample["inspection_summary"] = aggregate_vision_sample(
        records, "SAMPLE-TEST", "LOT-TEST", "PALLET-TEST"
    )["vision_summary"]
    report["lot_summary"] = build_lot_summary(report["samples"])
    sheet = openpyxl.load_workbook(BytesIO(export_qc_xlsx(report)))["Report"]
    html = render_qc_print(report)
    assert label_values(sheet, "Sample · frutos de esta revisión") == [12, 24, 6]
    assert label_values(sheet, "Sample · frutos acumulados") == [42]
    assert label_values(sheet, "Oleocellosis acumulada") == ["7 frutos · 16.6667 %"]
    assert "Revisión adicional 3 · caja adicional" in html
    assert "Sample · frutos acumulados</dt><dd>42" in html


def test_confirmed_report_shows_actual_decision_without_pending_status(report):
    report.update(inspector_confirmed=True, inspector_name="Inspector TEST", confirmed_at="2026-11-15T10:00:00Z")
    report["samples"][0].update(inspector_confirmed=True, inspector_final_decision="STANDARD")
    html = render_qc_print(report)
    sheet = openpyxl.load_workbook(BytesIO(export_qc_xlsx(report)))["Report"]
    assert "Estado inspector (pendiente de confirmación)" not in html
    assert "Decisión final del inspector</dt><dd>STANDARD" in html
    assert label_values(sheet, "Estado inspector (pendiente de confirmación)") == []
    assert label_values(sheet, "Decisión final del inspector") == ["STANDARD"]
    assert "Revisión adicional 2" in html


def test_reports_without_review_history_keep_the_existing_rendering(report):
    sample = report["samples"][0]
    sample.pop("review_history")
    sample.pop("review_choice")
    expected = render_qc_print(report)
    sample["review_history"] = None
    sample["review_choice"] = None
    assert render_qc_print(report) == expected
    assert "Historial de revisiones" not in expected
    sheet = openpyxl.load_workbook(BytesIO(export_qc_xlsx(report)))["Report"]
    assert not any(
        isinstance(cell.value, str) and cell.value.startswith("Historial de revisiones")
        for row in sheet for cell in row
    )
