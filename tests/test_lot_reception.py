"""Escanear una paleta prepara el lote completo con datos reales de recepción."""

from copy import deepcopy

import pytest

from smartfruit.reception import resolve_reception, resolve_reception_lot


def row(pallet_id="0001", **changes):
    result = {
        "scan_code": f"ERP-{pallet_id}",
        "lot_id": "LOT-01",
        "label_brand": "Example label",
        "country_origin": "Example country",
        "pallet_id": pallet_id,
        "size_declared": "150",
        "expected_count_per_box": "150",
        "shipment_id": "SHIP-01",
        "packing_date": "2026-11-01",
        "boxes_received": "",
    }
    result.update(changes)
    return result


def test_scan_gets_lot_and_all_its_pallets_in_source_order_only():
    records = [row("0001"), row("OTHER", lot_id="LOT-02"), row("0002"), row("0003")]
    original = deepcopy(records)
    result = resolve_reception_lot(records, "ERP-0002")
    assert result["lot_id"] == "LOT-01"
    assert result["scanned_pallet_id"] == "0002"
    assert result["qc_header"] == {"lot_id": "LOT-01", "country_origin": "Example country"}
    assert [pallet["pallet_id"] for pallet in result["pallets"]] == ["0001", "0002", "0003"]
    assert result["pallets"][1]["scan_input"] == "ERP-0002"
    assert result["records"] == [records[0], records[2], records[3]]
    assert result["inspector_required"] == []
    assert records == original
    result["records"][0]["label_brand"] = "Changed roster copy"
    result["pallets"][0]["records"][0]["label_brand"] = "Changed selection copy"
    assert records == original


def test_existing_single_pallet_selection_and_lot_expansion_are_compatible():
    records = [row("5824"), row("5825")]
    result = resolve_reception_lot(records, 5824)
    assert result["pallets"][0] == resolve_reception(records, 5824)
    assert result["pallets"][1] == resolve_reception(records, "5825")


def test_mixed_sizes_keep_raw_lines_and_require_inspector_without_building_a_range():
    records = [
        row("0001", size_declared="36", expected_count_per_box="36"),
        row("0001", scan_code="SIZE-42", size_declared="42", expected_count_per_box="42"),
        row("0001", scan_code="SIZE-42", size_declared="42", expected_count_per_box="42"),
        row("0002"),
    ]
    result = resolve_reception_lot(records, "0002")
    assert len(result["pallets"]) == 2
    mixed = result["pallets"][0]
    assert mixed["qc_fields"]["size"] == ""
    assert mixed["records"] == records[:3]
    assert result["records"] == records
    assert result["inspector_required"] == [{"pallet_id": "0001", "fields": ["size"]}]
    assert "avg_count_per_box" not in mixed["qc_fields"]


def test_explicit_optional_general_fields_are_precaptured_as_source_text():
    records = [
        row(
            "0001",
            grower="Grower from CSV",
            avg_count_per_box="36 - 42",
            plu_pct="70-80%",
            plu_coo="4048/Example",
            vessel="Source vessel",
            container="N/A",
        )
    ]
    result = resolve_reception_lot(records, "0001")
    qc = result["pallets"][0]["qc_fields"]
    assert qc["grower"] == "Grower from CSV"
    assert qc["packing_date"] == "2026-11-01"
    assert qc["avg_count_per_box"] == "36 - 42"
    assert qc["plu_pct"] == "70-80%"
    assert qc["plu_coo"] == "4048/Example"
    assert result["qc_header"]["vessel"] == "Source vessel"
    assert result["qc_header"]["container"] == "N/A"


def test_absent_or_unknown_fields_do_not_fabricate_measurements_or_fruit_origin():
    records = [
        row(
            "0001",
            country_origin="",
            label_brand="",
            size_declared="",
            packing_date="",
            expected_count_per_box="150",
            grower="",
            container="N/A",
            sample_count="999",
            pulp_temp="99",
            oleocellosis="99",
        )
    ]
    result = resolve_reception_lot(records, "0001")
    qc = result["pallets"][0]["qc_fields"]
    assert qc["grower"] == qc["packing_date"] == qc["size"] == qc["label_brand"] == ""
    assert "avg_count_per_box" not in qc
    assert "country_origin" not in result["qc_header"]
    assert result["qc_header"]["container"] == "N/A"
    assert not {"sample_count", "pulp_temp", "oleocellosis"}.intersection(qc)
    assert result["records"][0]["sample_count"] == "999"


def test_grower_or_date_mixtures_are_left_blank_and_explicitly_marked():
    records = [
        row("0001", grower="Grower A", packing_date="2026-11-01"),
        row("0001", grower="Grower B", packing_date="2026-11-02"),
    ]
    result = resolve_reception_lot(records, "0001")
    assert result["pallets"][0]["qc_fields"]["grower"] == ""
    assert result["pallets"][0]["qc_fields"]["packing_date"] == ""
    assert result["inspector_required"] == [
        {"pallet_id": "0001", "fields": ["packing_date", "grower"]}
    ]


def test_missing_grower_in_one_line_does_not_assert_pallet_wide_value():
    records = [row("0001", grower="Known"), row("0001")]
    result = resolve_reception_lot(records, "0001")
    assert result["pallets"][0]["qc_fields"]["grower"] == ""
    assert result["inspector_required"] == [{"pallet_id": "0001", "fields": ["grower"]}]


def test_header_is_shared_across_whole_lot_not_taken_only_from_scanned_pallet():
    records = [
        row("0001", vessel="Vessel A", container="A"),
        row("0002", country_origin="Other country", vessel="Vessel B", container="B"),
    ]
    result = resolve_reception_lot(records, "0001")
    assert result["qc_header"] == {"lot_id": "LOT-01"}
    assert result["pallets"][0]["qc_header"]["country_origin"] == "Example country"
    assert result["pallets"][1]["qc_header"]["country_origin"] == "Other country"


def test_same_pallet_ids_between_lots_need_context_before_expansion():
    records = [row("0001"), row("0001", lot_id="LOT-02"), row("0002", lot_id="LOT-02")]
    with pytest.raises(ValueError, match="ambiguo"):
        resolve_reception_lot(records, "0001")
    result = resolve_reception_lot(records, "0001", "LOT-02")
    assert result["lot_id"] == "LOT-02"
    assert [pallet["pallet_id"] for pallet in result["pallets"]] == ["0001", "0002"]


def test_unscanned_pallet_ambiguity_between_shipments_rejects_whole_expansion():
    records = [row("0001"), row("0002"), row("0002", shipment_id="SHIP-OTHER")]
    original = deepcopy(records)
    with pytest.raises(ValueError, match="ambiguo"):
        resolve_reception_lot(records, "0001")
    assert records == original


def test_distinct_pallets_in_distinct_shipments_of_same_lot_remain_separate():
    records = [row("0001"), row("0002", shipment_id="SHIP-OTHER")]
    result = resolve_reception_lot(records, "0001")
    assert [pallet["records"][0]["shipment_id"] for pallet in result["pallets"]] == [
        "SHIP-01",
        "SHIP-OTHER",
    ]


def test_optional_size_column_can_supply_unknown_declared_size_but_not_override_conflicts():
    explicit = resolve_reception_lot([row("0001", size_declared="", size="36 - 42")], "0001")
    assert explicit["pallets"][0]["qc_fields"]["size"] == "36 - 42"
    conflicting = resolve_reception_lot([row("0001", size_declared="150", size="175")], "0001")
    assert conflicting["pallets"][0]["qc_fields"]["size"] == ""
    assert conflicting["inspector_required"] == [{"pallet_id": "0001", "fields": ["size"]}]


@pytest.mark.parametrize("records", [None, {}, [], [row("0001", lot_id="")]])
def test_invalid_or_empty_source_does_not_create_a_lot(records):
    with pytest.raises(ValueError):
        resolve_reception_lot(records, "0001")


def test_explicit_lot_selection_opens_roster_without_claiming_a_scan():
    records = [row("0001"), row("OTHER", lot_id="LOT-02"), row("0002")]
    original = deepcopy(records)
    selected = resolve_reception_lot(records, lot_id=" LOT-01 ")
    assert selected["lot_id"] == "LOT-01"
    assert selected["selection_mode"] == "lot"
    assert selected["scanned_pallet_id"] is None
    assert "scan_input" not in selected
    assert selected["records"] == [records[0], records[2]]
    assert [pallet["pallet_id"] for pallet in selected["pallets"]] == ["0001", "0002"]
    assert selected["pallets"][0] == resolve_reception(records, "0001", "LOT-01")
    selected["records"][0]["label_brand"] = "Changed copy"
    assert records == original


def test_scan_result_retains_actual_input_and_selection_mode():
    result = resolve_reception_lot([row("0001"), row("0002")], " ERP-0002 ")
    assert result["selection_mode"] == "scan"
    assert result["scan_input"] == "ERP-0002"
    assert result["scanned_pallet_id"] == "0002"


@pytest.mark.parametrize("lot_id", [None, "", "UNKNOWN", True, 1.5])
def test_explicit_lot_selection_requires_a_valid_existing_lot(lot_id):
    with pytest.raises(ValueError):
        resolve_reception_lot([row("0001")], lot_id=lot_id)


def test_explicit_lot_selection_keeps_same_pallet_ids_in_other_lots_separate():
    records = [row("0001"), row("0001", lot_id="LOT-02"), row("0002", lot_id="LOT-02")]
    selected = resolve_reception_lot(records, lot_id="LOT-02")
    assert [pallet["pallet_id"] for pallet in selected["pallets"]] == ["0001", "0002"]
    assert all(record["lot_id"] == "LOT-02" for record in selected["records"])


def test_explicit_lot_selection_still_rejects_ambiguous_pallet_shipments():
    records = [row("0001"), row("0001", shipment_id="SHIP-02")]
    with pytest.raises(ValueError, match="ambiguo"):
        resolve_reception_lot(records, lot_id="LOT-01")
