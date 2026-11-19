"""Recepción por datos existentes: sin fabricar etiquetas, lotes ni mediciones QC."""

import csv
import io
from copy import deepcopy

import pytest

from smartfruit.reception import load_reception_manifest, manifest_summary, resolve_reception

FIELDS = [
    "scan_code",
    "lot_id",
    "label_brand",
    "country_origin",
    "pallet_id",
    "size_declared",
    "expected_count_per_box",
    "shipment_id",
    "packing_date",
    "boxes_received",
    "extra_from_erp",
]


def reception_row(**changes):
    row = {
        "scan_code": "ERP-CODE-01",
        "lot_id": "LOT-01",
        "label_brand": "Example label",
        "country_origin": "Example country",
        "pallet_id": "5824",
        "size_declared": "150",
        "expected_count_per_box": "150",
        "shipment_id": "SHIP-01",
        "packing_date": "2026-11-01",
        "boxes_received": "",
        "extra_from_erp": "Keep this value",
    }
    row.update(changes)
    return row


def csv_text(rows=None, *, delimiter=";", fields=FIELDS):
    target = io.StringIO(newline="")
    writer = csv.DictWriter(target, fieldnames=fields, delimiter=delimiter)
    writer.writeheader()
    writer.writerows([reception_row()] if rows is None else rows)
    return target.getvalue()


@pytest.mark.parametrize("delimiter", [";", ","])
def test_csv_bom_both_delimiters_and_all_source_forms(tmp_path, delimiter):
    text = "\ufeff" + csv_text(delimiter=delimiter)
    path = tmp_path / "reception.csv"
    path.write_text(text, encoding="utf-8")
    for source in (text, text.encode(), path, io.StringIO(text), io.BytesIO(text.encode())):
        assert load_reception_manifest(source) == [reception_row()]


def test_string_source_is_csv_content_never_a_filesystem_path(tmp_path):
    path = tmp_path / "reception.csv"
    path.write_text(csv_text(), encoding="utf-8")
    assert len(load_reception_manifest(path)) == 1
    with pytest.raises(ValueError):
        load_reception_manifest(str(path))


@pytest.mark.parametrize("scan", ["5824", 5824, "ERP-CODE-01"])
def test_exact_pallet_or_scan_code_resolves_existing_data(scan):
    selection = resolve_reception(load_reception_manifest(csv_text()), scan)
    assert selection["scan_input"] == str(scan)
    assert selection["lot_id"] == "LOT-01"
    assert selection["pallet_id"] == "5824"
    assert selection["qc_header"] == {"lot_id": "LOT-01", "country_origin": "Example country"}
    assert selection["qc_fields"] == {
        "pallet_id": "5824",
        "label_brand": "Example label",
        "packing_date": "2026-11-01",
        "size": "150",
    }
    assert selection["records"] == [reception_row()]
    assert "avg_count_per_box" not in selection["qc_fields"]
    assert "sample_count" not in selection["qc_fields"]
    assert "oleocellosis" not in selection["qc_fields"]


def test_leading_zero_ids_are_preserved_and_never_numerically_normalized():
    row = reception_row(pallet_id="005824", lot_id="0004", scan_code="00000020")
    records = load_reception_manifest(csv_text([row]))
    assert resolve_reception(records, "005824")["lot_id"] == "0004"
    assert resolve_reception(records, "00000020")["pallet_id"] == "005824"
    for scan in (5824, "5824", "20"):
        with pytest.raises(ValueError, match="Paleta no encontrada"):
            resolve_reception(records, scan)


def test_missing_pallet_does_not_parse_prefix_or_assume_lot():
    records = load_reception_manifest(csv_text())
    for scan in ("SF-LOT-01-5824", "LOT-01", "9999"):
        with pytest.raises(ValueError, match="Paleta no encontrada"):
            resolve_reception(records, scan)


def test_demo_lot_and_simple_pallet_are_matched_without_linking_other_lots():
    # Los nombres de columnas/valores de identificación reproducen la relación
    # de la demo; no se incluye el CSV operativo ni sus filas como fixture.
    records = load_reception_manifest(
        csv_text([reception_row(scan_code="SF-5815-5645", lot_id="5815", pallet_id="5645")])
    )
    assert resolve_reception(records, "5645")["lot_id"] == "5815"
    assert resolve_reception(records, "SF-5815-5645")["pallet_id"] == "5645"
    with pytest.raises(ValueError, match="Paleta no encontrada"):
        resolve_reception(records, "5824")
    with pytest.raises(ValueError, match="Paleta no encontrada"):
        resolve_reception(records, "5645", lot_id="5878")


def test_same_pallet_in_two_lots_requires_context_and_accepts_integer_context():
    records = [reception_row(lot_id="123"), reception_row(lot_id="456")]
    with pytest.raises(ValueError, match="ambiguo"):
        resolve_reception(records, "5824")
    result = resolve_reception(records, "5824", lot_id=123)
    assert result["lot_id"] == "123"
    assert len(result["records"]) == 1


def test_same_pallet_and_lot_in_two_shipments_is_still_ambiguous():
    records = [reception_row(shipment_id="SHIP-1"), reception_row(shipment_id="SHIP-2")]
    with pytest.raises(ValueError, match="ambiguo"):
        resolve_reception(records, "5824", lot_id="LOT-01")


def test_same_scan_code_for_two_pallets_is_ambiguous():
    records = [reception_row(pallet_id="5824"), reception_row(pallet_id="5825")]
    with pytest.raises(ValueError, match="ambiguo"):
        resolve_reception(records, "ERP-CODE-01")


def test_scan_code_or_pallet_collision_across_records_is_ambiguous():
    records = [reception_row(), reception_row(scan_code="5824", pallet_id="9999")]
    with pytest.raises(ValueError, match="ambiguo"):
        resolve_reception(records, "5824")


def test_mixed_sizes_keep_all_lines_but_do_not_pick_one_size():
    records = [
        reception_row(scan_code="SIZE-1", size_declared="150"),
        reception_row(scan_code="SIZE-2", size_declared="175", expected_count_per_box="175"),
    ]
    before = deepcopy(records)
    result = resolve_reception(records, "SIZE-1")
    assert result["records"] == before
    assert result["qc_fields"]["size"] == ""
    assert "avg_count_per_box" not in result["qc_fields"]
    result["records"][0]["label_brand"] = "Changed by caller"
    assert records == before


def test_diverse_brand_country_and_packing_date_are_not_silently_selected():
    records = [
        reception_row(),
        reception_row(label_brand="Other", country_origin="Other", packing_date="2026-11-02"),
    ]
    result = resolve_reception(records, "5824")
    assert result["qc_header"] == {"lot_id": "LOT-01"}
    assert result["qc_fields"]["label_brand"] == ""
    assert result["qc_fields"]["packing_date"] == ""
    assert len(result["records"]) == 2


def test_blank_values_remain_unknown_and_extra_csv_fields_survive():
    row = reception_row(
        scan_code="",
        label_brand="",
        country_origin="",
        size_declared="",
        expected_count_per_box="",
        packing_date="",
    )
    records = load_reception_manifest(csv_text([row]))
    assert records == [row]
    assert records[0]["boxes_received"] == ""
    assert records[0]["extra_from_erp"] == "Keep this value"
    result = resolve_reception(records, "5824")
    assert result["qc_header"] == {"lot_id": "LOT-01"}
    assert result["qc_fields"]["size"] == ""


def test_known_value_plus_unknown_value_does_not_assert_pallet_wide_brand():
    result = resolve_reception([reception_row(), reception_row(label_brand="")], "5824")
    assert result["qc_fields"]["label_brand"] == ""


@pytest.mark.parametrize("field", ["lot_id", "pallet_id"])
def test_blank_required_ids_rejected(field):
    with pytest.raises(ValueError, match=field):
        load_reception_manifest(csv_text([reception_row(**{field: " "})]))


def test_duplicate_headers_are_rejected_including_whitespace_aliases():
    with pytest.raises(ValueError, match="cabeceras duplicadas"):
        load_reception_manifest(csv_text().replace("extra_from_erp", " pallet_id ", 1))


def test_missing_required_header_is_rejected():
    with pytest.raises(ValueError, match="campos requeridos"):
        load_reception_manifest(csv_text().replace("expected_count_per_box", "something_else", 1))


@pytest.mark.parametrize(
    "text",
    ["", "\ufeff", "not CSV", csv_text(rows=[]), csv_text() + ";\n", csv_text() + ";" * 10],
)
def test_empty_and_malformed_manifests_are_rejected(text):
    with pytest.raises(ValueError):
        load_reception_manifest(text.encode())


def test_malformed_quoted_csv_is_rejected():
    with pytest.raises(ValueError, match="CSV mal formado"):
        load_reception_manifest(csv_text(rows=[]) + '"unterminated')


def test_blank_header_is_rejected():
    with pytest.raises(ValueError, match="columna sin nombre"):
        load_reception_manifest(csv_text().replace("extra_from_erp", "", 1))


@pytest.mark.parametrize("scan", ["", "  ", None, True, 5824.0])
def test_invalid_scan_input_rejected(scan):
    with pytest.raises(ValueError):
        resolve_reception([reception_row()], scan)


def test_records_passed_directly_are_also_validated():
    for records in (
        [{"pallet_id": "5824"}],
        [reception_row(lot_id=123)],
        [reception_row(extra_from_erp={"nested": "data"})],
        [reception_row(extra_from_erp=None)],
        None,
        {"pallet_id": "5824"},
    ):
        with pytest.raises(ValueError):
            resolve_reception(records, "5824")


def test_summary_counts_unique_shipment_lot_pallet_without_dropping_raw_duplicates():
    records = [
        reception_row(),
        reception_row(),
        reception_row(size_declared="175"),
        reception_row(shipment_id="SHIP-02"),
        reception_row(lot_id="LOT-02"),
        reception_row(pallet_id="5825"),
    ]
    summary = manifest_summary(records)
    assert summary == {
        "records": records,
        "lot_ids": ["LOT-01", "LOT-02"],
        "pallets_count": 4,
    }
    summary["records"][0]["label_brand"] = "Edited copy"
    assert records[0]["label_brand"] == "Example label"
    result = resolve_reception(records[:3], "5824")
    assert result["records"] == records[:3]
    assert result["qc_fields"]["size"] == ""


def test_summary_empty_or_malformed_records():
    assert manifest_summary([]) == {"records": [], "lot_ids": [], "pallets_count": 0}
    with pytest.raises(ValueError):
        manifest_summary([reception_row(pallet_id="")])
