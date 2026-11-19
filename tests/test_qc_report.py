"""Meaningful workbook checks without needing Excel or the private originals."""

import unittest
from copy import deepcopy
from importlib.resources import files
from io import BytesIO
from zipfile import ZipFile

import openpyxl

from smartfruit.qc_report import QC_FIELDS, export_qc_xlsx


def example_report():
    fields = dict.fromkeys(QC_FIELDS)
    fields.update(
        {
            "label_brand": "DEMO",
            "pallet_id": "PALLET_DEMO_01",
            "grower": "N/A",
            "packing_date": "2026-11-13",
            "size": "42",
            "avg_count_per_box": 42,
            "plu_pct": "70",
            "plu_coo": "DEMO",
            "sample_count": 12,
            "open_rating": "Good",
            "color_rating": "Good",
            "pulp_temp": 50.0,
        }
    )
    fields.update(dict.fromkeys(QC_FIELDS[12:], 0))
    fields["oleocellosis"] = 1
    fields["scars"] = 2
    sample = {
        "sample_id": "SAMPLE_DEMO_01",
        "pallet_id": "PALLET_DEMO_01",
        "qc_fields": fields,
        "inspection_summary": {
            "total_fruits": 12,
            "oleocellosis_count": 1,
            "oleocellosis_pct": 100 / 12,
            "mean_confidence": 0.95,
            "image_ids": ["IMG_DEMO_01"],
            "duplicate_image_ids_ignored": [],
            "low_confidence_count": 0,
            "low_confidence_threshold": 0.7,
        },
        "business_severity": {
            "business_max_level": 2,
            "quality_max_level": 2,
            "condition_max_level": 2,
            "boundary_policy": "higher",
            "recommendation": "EXPAND",
            "reasons": ["Oleocelosis", "Cicatrices / defectos de piel"],
        },
        "final_recommendation": "EXPAND",
        "recommendation_reasons": ["Oleocelosis", "Cicatrices / defectos de piel"],
        "predictive": {"enabled": False, "experimental": True, "decision": None},
        "inspector_final_decision": None,
        "inspector_confirmed": False,
        "observations": "",
        "rule_coverage": {
            "evaluated": ["Oleocellosis", "Scars"],
            "not_evaluated": ["Soft", "Wounds", "Int. Dryness", "Black tips"],
        },
    }
    return {
        "schema_version": "1.1",
        "lot_id": "LOT_DEMO_01",
        "qc_header": {
            "inspection_date": "2026-11-13",
            "lot_id": "LOT_DEMO_01",
            "country_origin": "Mexico",
            "vessel": "N/A",
            "container": "N/A",
            "remarks": "Observación de demostración",
            "Level_Flag": 2,
            "reason": "Criterio del inspector",
            "grade": "Good",
            "color": "Green",
            "plu_pct": "70%",
        },
        "inspector_name": "Inspector DEMO",
        "observations": "Observaciones del reporte",
        "inspector_confirmed": False,
        "confirmed_at": None,
        "samples": [sample],
    }


def load(data, *, values=False):
    return openpyxl.load_workbook(BytesIO(data), data_only=values)


def strings(sheet):
    return [cell.value for row in sheet for cell in row if isinstance(cell.value, str)]


def receipt_record():
    return {
        "scan_code": "SF-LOT_DEMO-PALLET_DEMO",
        "scan_level": "PALLET",
        "lot_id": "LOT_DEMO_01",
        "pallet_id": "PALLET_DEMO_01",
        "size_declared": "110",
        "expected_count_per_box": "110",
        "boxes_received": "",
        "qty_received_weight": "",
        "label_brand": "DEMO",
        "country_origin": "Mexico",
        "shipment_id": "SHIP_DEMO_01",
        "data_origin": "REAL_QC + SIM_IDS",
        "source_record": "QC_DEMO.pdf",
        "status": "READY",
    }


def label_values(sheet, label):
    return [
        sheet.cell(row, 9).value
        for row in range(1, sheet.max_row + 1)
        if sheet.cell(row, 1).value == label
    ]


class QCReportTests(unittest.TestCase):
    def test_blank_template_contains_only_original_labels(self):
        resource = files("smartfruit").joinpath("resources/qc_template.xlsx")
        workbook = load(resource.read_bytes())
        self.assertEqual(workbook.sheetnames, ["Report"])
        sheet = workbook["Report"]
        expected_nonempty = {
            "J2",
            "Q2",
            "U2",
            "X2",
            "AB2",
            "J4",
            "AB5",
            "J6",
            "J8",
            "AB8",
            "J10",
            "A14",
            "J14",
            "V14",
            "I25",
            "I26",
        } | {f"{openpyxl.utils.get_column_letter(col)}15" for col in range(1, 30)}
        actual_nonempty = {
            cell.coordinate for row in sheet for cell in row if cell.value is not None
        }
        self.assertEqual(actual_nonempty, expected_nonempty)
        self.assertFalse(any(cell.data_type == "f" for row in sheet for cell in row))
        self.assertFalse(any(cell.comment or cell.hyperlink for row in sheet for cell in row))
        self.assertEqual(workbook.properties.creator, "SmartFruit")
        self.assertIsNone(workbook.properties.lastModifiedBy)
        self.assertIsNone(workbook.properties.lastPrinted)
        self.assertFalse(any(d.hidden for d in sheet.row_dimensions.values()))
        self.assertFalse(any(d.hidden for d in sheet.column_dimensions.values()))
        self.assertEqual(len(sheet._images), 1)
        self.assertEqual(len(workbook._external_links), 0)
        self.assertEqual(len(workbook.defined_names), 0)

    def test_real_layout_quantities_and_cached_totals(self):
        report = example_report()
        before = deepcopy(report)
        data = export_qc_xlsx(report)
        self.assertEqual(report, before, "Export must not mutate inspection data")
        workbook = load(data)
        self.assertEqual(workbook.sheetnames, ["Report"])
        sheet = workbook["Report"]
        for address, label in {
            "A14": "General Information",
            "J14": "Condition",
            "V14": "Quality",
            "I15": "Sample ",
            "R15": "Oleocellosis",
            "W15": "Scars",
            "AC15": "Total Percent of each sample",
        }.items():
            self.assertEqual(sheet[address].value, label)
        self.assertEqual(sheet["I16"].value, 12)
        self.assertEqual(sheet["R16"].value, 1)
        self.assertEqual(sheet["W16"].value, 2)
        self.assertEqual(sheet["U2"].value, "Level Flag: 2")
        self.assertEqual(sheet["I18"].value, "Total Percent of each column")
        self.assertEqual(sheet["I19"].value, "Total Percent Combined")
        self.assertEqual(sheet["AC16"].data_type, "f")
        self.assertEqual(len(sheet._images), 1)
        values = load(data, values=True)["Report"]
        self.assertEqual(values["I17"].value, 12)
        self.assertEqual(values["R17"].value, 1)
        self.assertEqual(values["L17"].value, 50.0)
        self.assertAlmostEqual(values["AC16"].value, 3 / 12)
        self.assertAlmostEqual(values["R18"].value, 1 / 12)
        self.assertAlmostEqual(values["M19"].value, 3 / 12)

    def test_off_omits_predicted_loss_and_marks_draft(self):
        sheet = load(export_qc_xlsx(example_report()))["Report"]
        text = "\n".join(strings(sheet))
        self.assertIn("BORRADOR", text)
        self.assertNotIn("predicted_loss_pct", text)
        self.assertIn("OFF", strings(sheet))
        self.assertIn("Sin regla implementada: Soft", text)
        self.assertIn("confirmados QC: 1", text)
        self.assertNotIn("confianza media:", text)

    def test_vision_counts_ending_in_zero_are_not_truncated(self):
        report = example_report()
        report["samples"][0]["inspection_summary"].update(
            {
                "total_fruits": 100,
                "oleocellosis_count": 20,
                "oleocellosis_pct": 20.0,
            }
        )
        sheet = load(export_qc_xlsx(report))["Report"]
        text = "\n".join(strings(sheet))
        self.assertIn("Frutos evaluados: 100; confirmados QC: 20;", text)

    def test_confirmation_and_human_override_do_not_change_level_flag(self):
        report = example_report()
        report["inspector_confirmed"] = True
        report["confirmed_at"] = "2026-11-13T15:00:00Z"
        sample = report["samples"][0]
        sample["inspector_confirmed"] = True
        sample["inspector_final_decision"] = "ESCALATE"
        sheet = load(export_qc_xlsx(report))["Report"]
        text = "\n".join(strings(sheet))
        self.assertIn("SmartFruit · CONFIRMADO", text)
        self.assertIn("13/11/2026 10:00:00 (America/Lima)", text)
        self.assertIn("EXPAND", strings(sheet))
        self.assertIn("ESCALATE", strings(sheet))
        self.assertEqual(sheet["U2"].value, "Level Flag: 2")
        self.assertNotIn("BORRADOR", text)

    def test_false_confirmation_is_not_printed_as_final(self):
        report = example_report()
        report["inspector_confirmed"] = True
        report["confirmed_at"] = "2026-11-13T15:00:00Z"
        # Missing sample confirmation and final decision cannot certify the report.
        sheet = load(export_qc_xlsx(report))["Report"]
        self.assertIn("BORRADOR", "\n".join(strings(sheet)))

    def test_predictive_on_displays_signal_without_changing_recommendation(self):
        report = example_report()
        report["samples"][0]["predictive"] = {
            "enabled": True,
            "experimental": True,
            "predicted_loss_pct": 12.5,
        }
        sheet = load(export_qc_xlsx(report))["Report"]
        text = "\n".join(strings(sheet))
        self.assertIn("ON - Experimental", text)
        self.assertIn("predicted_loss_pct", text)
        self.assertIn("12.5 %", text)
        self.assertIn("EXPAND", strings(sheet))

    def test_more_than_eight_samples_are_not_truncated(self):
        report = example_report()
        report["samples"] = [deepcopy(report["samples"][0]) for _ in range(10)]
        for i, sample in enumerate(report["samples"]):
            sample["sample_id"] = f"SAMPLE_DEMO_{i:02}"
            sample["qc_fields"]["pallet_id"] = f"PALLET_DEMO_{i:02}"
        data = export_qc_xlsx(report)
        sheet = load(data)["Report"]
        self.assertEqual(sheet["B25"].value, "PALLET_DEMO_09")
        self.assertEqual(sheet["I27"].value, "Total Percent of each column")
        values = load(data, values=True)["Report"]
        self.assertEqual(values["I26"].value, 120)
        self.assertEqual(values["R26"].value, 10)
        self.assertEqual(values["W26"].value, 20)
        self.assertAlmostEqual(values["M28"].value, 0.25)
        self.assertIn("SAMPLE_DEMO_09", "\n".join(strings(sheet)))

    def test_inspector_text_cannot_become_formula(self):
        report = example_report()
        report["qc_header"]["remarks"] = '=HYPERLINK("https://invalid.example","test")'
        report["samples"][0]["qc_fields"]["label_brand"] = "+1+1"
        report["observations"] = "=1+1"
        data = export_qc_xlsx(report)
        sheet = load(data)["Report"]
        self.assertEqual(sheet["Q3"].data_type, "s")
        self.assertEqual(sheet["Q3"].value, report["qc_header"]["remarks"])
        self.assertEqual(sheet["A16"].data_type, "s")
        for row in sheet:
            for cell in row:
                if cell.value == "=1+1":
                    self.assertEqual(cell.data_type, "s")
        # The operational text never appears inside a formula XML element.
        with ZipFile(BytesIO(data)) as archive:
            xml = archive.read("xl/worksheets/sheet1.xml").decode()
            self.assertNotIn("<f>HYPERLINK", xml)
            self.assertNotIn("<ns0:f>HYPERLINK", xml)

    def test_missing_counts_remain_blank_in_draft_totals(self):
        report = example_report()
        report["samples"][0]["qc_fields"]["mold"] = None
        data = export_qc_xlsx(report)
        sheet = load(data, values=True)["Report"]
        self.assertIsNone(sheet["O16"].value)
        self.assertIsNone(sheet["O17"].value)
        self.assertIsNone(sheet["O18"].value)
        self.assertIsNone(sheet["AC16"].value)
        self.assertIsNone(sheet["M19"].value)

    def test_empty_report_is_rejected(self):
        report = example_report()
        report["samples"] = []
        with self.assertRaises(ValueError):
            export_qc_xlsx(report)

    def test_reception_preserves_unrecorded_quantities_instead_of_zero(self):
        report = example_report()
        record = receipt_record()
        record["qty_received_weight"] = None
        record["expected_count_per_box"] = "  "
        report["samples"][0]["reception"] = {
            "scan_input": record["scan_code"],
            "records": [record],
        }
        before = deepcopy(report)
        sheet = load(export_qc_xlsx(report))["Report"]
        self.assertEqual(report, before)
        self.assertEqual(label_values(sheet, "Cajas recibidas"), ["No registrado"])
        self.assertEqual(label_values(sheet, "Peso recibido"), ["No registrado"])
        self.assertEqual(label_values(sheet, "Frutos DECLARADOS por caja"), ["No registrado"])
        self.assertEqual(label_values(sheet, "Lectura escaneada"), [record["scan_code"]])

    def test_reception_includes_populated_quantities_and_provenance(self):
        report = example_report()
        record = receipt_record()
        record.update({"boxes_received": "24", "qty_received_weight": "150.5"})
        report["samples"][0]["reception"] = {
            "scan_input": record["scan_code"],
            "records": [record],
        }
        sheet = load(export_qc_xlsx(report))["Report"]
        text = "\n".join(strings(sheet))
        self.assertIn("Recepción · Checker y sistema actual", text)
        self.assertIn("AgroPeru Lot Number: LOT_DEMO_01; N° PALLET: PALLET_DEMO_01", text)
        self.assertIn("Label: DEMO; Size declared: 110", text)
        self.assertIn("Country Of Origin: Mexico; Envío: SHIP_DEMO_01", text)
        self.assertIn(
            "Procedencia: REAL_QC + SIM_IDS; Referencia: QC_DEMO.pdf; Estado: READY", text
        )
        self.assertIn("Código de etiqueta: SF-LOT_DEMO-PALLET_DEMO; Alcance: PALLET", text)
        self.assertEqual(label_values(sheet, "Cajas recibidas"), ["24"])
        self.assertEqual(label_values(sheet, "Peso recibido"), ["150.5"])
        self.assertEqual(label_values(sheet, "Frutos DECLARADOS por caja"), ["110"])

    def test_mixed_reception_sizes_do_not_replace_measured_qc_or_vision(self):
        report = example_report()
        original = export_qc_xlsx(report)
        first = receipt_record()
        second = dict(first, size_declared="150", expected_count_per_box="150")
        report["samples"][0]["reception"] = {
            "scan_input": first["scan_code"],
            "records": [first, second],
        }
        enriched = export_qc_xlsx(report)
        old_sheet = load(original)["Report"]
        sheet = load(enriched)["Report"]
        self.assertEqual(label_values(sheet, "Frutos DECLARADOS por caja"), ["110", "150"])
        self.assertEqual(
            label_values(sheet, "Marca / tamaño declarado"),
            [
                "Label: DEMO; Size declared: 110",
                "Label: DEMO; Size declared: 150",
            ],
        )
        # The original first section, formulas and measured sample fields are intact.
        for row in old_sheet:
            for old_cell in row:
                self.assertEqual(sheet[old_cell.coordinate].value, old_cell.value)
                self.assertEqual(sheet[old_cell.coordinate].data_type, old_cell.data_type)
        self.assertEqual(sheet["E16"].value, "42")
        self.assertEqual(sheet["F16"].value, 42)
        self.assertEqual(sheet["I16"].value, 12)
        self.assertEqual(sheet["R16"].value, 1)
        self.assertAlmostEqual(load(enriched, values=True)["Report"]["M19"].value, 3 / 12)

    def test_reception_absence_preserves_prior_output_and_multiline_is_not_truncated(self):
        report = example_report()
        without = load(export_qc_xlsx(report))["Report"]
        self.assertNotIn("Recepción · Checker y sistema actual", strings(without))
        record = receipt_record()
        scan = "SF-LOT_DEMO-PALLET_DEMO\nEtiqueta secundaria"
        report["samples"][0]["reception"] = {"scan_input": scan, "records": [record]}
        sheet = load(export_qc_xlsx(report))["Report"]
        row = next(
            row
            for row in range(1, sheet.max_row + 1)
            if sheet.cell(row, 1).value == "Lectura escaneada"
        )
        self.assertEqual(sheet.cell(row, 9).value, scan)
        self.assertTrue(sheet.cell(row, 9).alignment.wrap_text)
        self.assertGreaterEqual(sheet.row_dimensions[row].height, 45)


if __name__ == "__main__":
    unittest.main()
