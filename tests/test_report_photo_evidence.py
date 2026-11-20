"""Defect photos are embedded without exposing filenames in the final report."""

import base64
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import openpyxl
import pytest
from PIL import Image

from smartfruit.print_report import render_qc_print
from smartfruit.qc_report import QC_FIELDS, export_qc_xlsx


@pytest.fixture
def photo():
    data = BytesIO()
    Image.new("RGB", (64, 48), color=(180, 180, 30)).save(data, format="JPEG")
    return {
        "evidence_id": "INTERNAL-EVIDENCE-ID",
        "image_id": "IMG_PRIVATE_SOURCE_1234",
        "crop_id": "PRIVATE_CROP_01",
        "source_filename": "PRIVATE_FRUIT_PHOTO.jpg",
        "image_data_url": "data:image/jpeg;base64," + base64.b64encode(data.getvalue()).decode(),
        "sample_box_id": "BOX_001",
        "defect": "oleocellosis",
        "view": "fruit_crop",
        "affected_fruits": 1,
        "width": 64,
        "height": 48,
        "caption": "DO NOT PRINT PRIVATE_FRUIT_PHOTO.jpg OR PRIVATE_CROP_01",
    }


@pytest.fixture
def report(photo):
    fields = dict.fromkeys(QC_FIELDS, "")
    fields.update(dict.fromkeys(QC_FIELDS[12:], 0))
    fields.update(pallet_id="P1", sample_count=12, oleocellosis=1)
    return {
        "qc_header": {"lot_id": "L1", "inspection_date": "2026-11-16"},
        "samples": [{
            "sample_id": "S1", "pallet_id": "P1", "qc_fields": fields,
            "inspection_summary": {
                "total_fruits": 12, "oleocellosis_count": 1,
                "oleocellosis_pct": 100 / 12, "images_processed": 2,
                "image_ids": ["IMG_PRIVATE_SOURCE_1234", "SECOND_PRIVATE_SOURCE"],
                "duplicate_image_ids_ignored": ["IMG_PRIVATE_SOURCE_1234"],
            },
            "evidence_photos": [photo],
            "evidence_summary": {
                "status": "available", "positive_fruits": 1, "attached_fruits": 1,
                "attached_photos": 1, "unavailable_fruits": 0,
            },
        }],
    }


def all_text(book):
    return "\n".join(
        str(cell.value) for sheet in book for row in sheet for cell in row if cell.value is not None
    )


def test_excel_and_self_contained_print_embed_defect_photos_without_names(report, photo):
    before = deepcopy(report)
    output = export_qc_xlsx(report)
    book = openpyxl.load_workbook(BytesIO(output))
    assert book.sheetnames == ["Report", "Evidencia"]
    assert book["Report"]["I16"].value == 12 and book["Report"]["R16"].value == 1
    assert len(book["Report"]._images) == 1  # The original QC logo remains on its own sheet.
    assert len(book["Evidencia"]._images) == 1
    with ZipFile(BytesIO(output)) as archive:
        assert len([name for name in archive.namelist() if name.startswith("xl/media/")]) == 2
    html = render_qc_print(report)
    assert f'src="{photo["image_data_url"]}"' in html
    assert "Paleta P1 · Caja BOX_001 · Oleocelosis · Fruto observado · Fotografía 1" in html
    assert "Fotografías procesadas</dt><dd>2" in html
    text = all_text(book)
    assert "Fotografías procesadas: 2; duplicados ignorados: 1" in text
    for hidden in (
        "IMG_PRIVATE_SOURCE_1234", "SECOND_PRIVATE_SOURCE", "PRIVATE_FRUIT_PHOTO.jpg",
        "PRIVATE_CROP_01", "INTERNAL-EVIDENCE-ID", "DO NOT PRINT",
    ):
        assert hidden not in html and hidden not in text
    assert report == before


def test_positive_fruit_without_available_photo_does_not_generate_a_fake_image(report):
    sample = report["samples"][0]
    sample["evidence_photos"] = []
    sample["evidence_summary"].update(
        status="unavailable", attached_photos=0, attached_fruits=0, unavailable_fruits=1,
    )
    book = openpyxl.load_workbook(BytesIO(export_qc_xlsx(report)))
    html = render_qc_print(report)
    message = "No se adjuntaron fotografías de los frutos con oleocelosis detectada."
    assert message in html and message in all_text(book)
    assert book.sheetnames == ["Report"] and html.count("<img ") == 1  # Only the original logo.


def test_no_defects_produces_no_missing_defect_photo_notice(report):
    sample = report["samples"][0]
    sample["evidence_photos"] = []
    sample["inspection_summary"]["oleocellosis_count"] = 0
    sample["evidence_summary"] = {"status": "no_defects", "positive_fruits": 0}
    html = render_qc_print(report)
    text = all_text(openpyxl.load_workbook(BytesIO(export_qc_xlsx(report))))
    assert "No se adjuntaron fotografías" not in html and "No se adjuntaron fotografías" not in text
    assert "photo-evidence\"><h4>" not in html


@pytest.mark.parametrize("keep_photo", [True, False])
def test_zero_confirmed_count_hides_stale_photos_and_stale_availability_notices(report, keep_photo):
    sample = report["samples"][0]
    sample["inspection_summary"]["oleocellosis_count"] = 0
    sample["qc_fields"]["oleocellosis"] = 0
    if not keep_photo:
        sample["evidence_photos"] = []
    book = openpyxl.load_workbook(BytesIO(export_qc_xlsx(report)))
    html = render_qc_print(report)
    assert book.sheetnames == ["Report"]
    assert html.count("<img ") == 1
    assert "No se adjuntaron fotografías" not in html
    assert "No se adjuntaron fotografías" not in all_text(book)


def test_saved_rejected_photo_is_hidden_while_confirmed_photo_stays(report):
    confirmed = report["samples"][0]["evidence_photos"][0]
    confirmed["vision_reviews"] = [{"review_status": "confirmed"}]
    rejected = deepcopy(confirmed)
    rejected["sample_box_id"] = "BOX_REJECTED"
    rejected["vision_reviews"] = [{"review_status": "rejected", "qc_included": False}]
    report["samples"][0]["evidence_photos"].append(rejected)
    book = openpyxl.load_workbook(BytesIO(export_qc_xlsx(report)))
    html = render_qc_print(report)
    assert len(book["Evidencia"]._images) == 1
    assert html.count("<img ") == 2  # QC logo and the confirmed photo.
    assert "BOX_REJECTED" not in html
    assert "BOX_REJECTED" not in all_text(book)


@pytest.mark.parametrize("change", [
    {"defect": "healthy"}, {"affected_fruits": 0},
    {"image_data_url": "https://example.invalid/PRIVATE_FRUIT_PHOTO.jpg"},
    {"image_data_url": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="},
    {"image_data_url": "data:image/jpeg;base64,not valid base64"},
])
def test_healthy_external_or_invalid_items_are_not_rendered_as_defect_photos(report, change):
    report["samples"][0]["evidence_photos"][0].update(change)
    book = openpyxl.load_workbook(BytesIO(export_qc_xlsx(report)))
    html = render_qc_print(report)
    assert book.sheetnames == ["Report"] and html.count("<img ") == 1
    assert "No se adjuntaron fotografías de los frutos con oleocelosis detectada." in html


def test_partial_photos_keep_the_remaining_missing_evidence_explicit(report):
    report["samples"][0]["evidence_summary"].update(
        status="partial", positive_fruits=3, unavailable_fruits=2,
    )
    html = render_qc_print(report)
    text = all_text(openpyxl.load_workbook(BytesIO(export_qc_xlsx(report))))
    assert "algunos frutos con oleocelosis no tienen fotografía adjunta" in html
    assert "algunos frutos con oleocelosis no tienen fotografía adjunta" in text
