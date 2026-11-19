"""Consulta del manifest de recepción existente, sin generar etiquetas ni códigos.

Los identificadores y las celdas CSV se conservan como texto. Los campos vacíos
representan información desconocida; no se convierten en cero ni se completan
con identificadores inferidos.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from copy import deepcopy
from os import PathLike
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = frozenset(
    {
        "scan_code",
        "lot_id",
        "label_brand",
        "country_origin",
        "pallet_id",
        "size_declared",
        "expected_count_per_box",
    }
)

# Nombres ya existentes en el manifest y en el QC. Las columnas QC opcionales
# solo se usan si la fuente realmente las incluye, sin crear aliases de ERP.
QC_GENERAL_SOURCES = {
    "label_brand": ("label_brand",),
    "packing_date": ("packing_date",),
    "size": ("size_declared", "size"),
    "grower": ("grower",),
    "avg_count_per_box": ("avg_count_per_box",),
    "plu_pct": ("plu_pct",),
    "plu_coo": ("plu_coo",),
}
OPTIONAL_GENERAL_FIELDS = ("grower", "avg_count_per_box", "plu_pct", "plu_coo")
HEADER_SOURCE_FIELDS = ("country_origin", "vessel", "container")


def _read_text(source: Any) -> str:
    try:
        if isinstance(source, (bytes, bytearray)):
            text = bytes(source).decode("utf-8-sig")
        elif isinstance(source, PathLike):
            text = Path(source).read_text(encoding="utf-8-sig")
        elif hasattr(source, "read"):
            text = source.read()
            if isinstance(text, bytes):
                text = text.decode("utf-8-sig")
        elif isinstance(source, str):
            # El backend recibe contenido CSV, nunca una ruta arbitraria enviada
            # por HTTP. Las rutas locales requieren un PathLike explícito.
            text = source
        else:
            raise ValueError("El manifest debe ser CSV, bytes, una ruta o un archivo abierto")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"No se pudo leer el manifest de recepción: {exc}") from exc
    if not isinstance(text, str):
        raise ValueError("El contenido del manifest debe ser texto CSV")
    return text.lstrip("\ufeff")


def _identifier(value: Any, name: str) -> str:
    """Acepta escaneo numérico entero sin perder ceros de entradas textuales."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{name} debe ser texto o un número entero")
    result = str(value).strip()
    if not result:
        raise ValueError(f"{name} no puede estar vacío")
    return result


def _validate_record(record: Any, row_number: int) -> None:
    if not isinstance(record, Mapping):
        raise ValueError(f"Manifest fila {row_number}: se esperaba un registro")
    missing = REQUIRED_FIELDS - record.keys()
    if missing:
        raise ValueError(f"Manifest fila {row_number}: faltan campos {sorted(missing)}")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in record.items()):
        raise ValueError(f"Manifest fila {row_number}: las celdas deben conservarse como texto")
    for key in ("lot_id", "pallet_id"):
        if not record[key].strip():
            raise ValueError(f"Manifest fila {row_number}: {key} no puede estar vacío")


def load_reception_manifest(source: Any) -> list[dict[str, str]]:
    """Lee CSV con BOM opcional y delimitador ``;`` o ``,``.

    Exige las columnas del manifest del proyecto y lot/pallet en cada fila.
    Preserva todas las columnas y sus celdas como texto, incluidos ceros iniciales
    y campos vacíos. Un str es contenido CSV; las rutas locales se pasan como
    pathlib.Path. Rechaza cabeceras repetidas y filas de longitud incorrecta.
    """
    text = _read_text(source)
    if not text.strip():
        raise ValueError("El manifest de recepción está vacío")
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    try:
        dialect = csv.Sniffer().sniff(first_line, delimiters=";,")
    except csv.Error as exc:
        raise ValueError("No se reconoció una cabecera CSV separada por ';' o ','") from exc
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=dialect.delimiter, strict=True)
        header_row = next((row for row in reader if row), None)
        if header_row is None:
            raise ValueError("El manifest de recepción está vacío")
        headers = [value.strip() for value in header_row]
        if any(not header for header in headers):
            raise ValueError("El manifest contiene una columna sin nombre")
        if len(headers) != len(set(headers)):
            raise ValueError("El manifest contiene cabeceras duplicadas")
        missing = REQUIRED_FIELDS - set(headers)
        if missing:
            raise ValueError(f"El manifest no contiene los campos requeridos: {sorted(missing)}")

        records: list[dict[str, str]] = []
        for row in reader:
            if not row:
                # Las líneas físicas vacías son separadores, no registros.
                continue
            if len(row) != len(headers):
                raise ValueError(
                    f"Manifest fila {reader.line_num}: número de celdas distinto de la cabecera"
                )
            if not any(value.strip() for value in row):
                raise ValueError(f"Manifest fila {reader.line_num}: registro vacío")
            record = dict(zip(headers, row, strict=True))
            _validate_record(record, reader.line_num)
            records.append(record)
    except csv.Error as exc:
        raise ValueError(f"El manifest contiene CSV mal formado: {exc}") from exc
    if not records:
        raise ValueError("El manifest de recepción no contiene registros")
    return records


def _group_key(record: Mapping[str, str]) -> tuple[str, str, str]:
    return (
        record["lot_id"].strip(),
        record["pallet_id"].strip(),
        record.get("shipment_id", "").strip(),
    )


def _unambiguous(records: list[dict[str, str]], name: str) -> str:
    """No elegir la primera fila si hay valores distintos, incluso desconocidos."""
    values = {record.get(name, "").strip() for record in records}
    return next(iter(values)) if len(values) == 1 else ""


def _qc_values(records: list[dict[str, str]], name: str) -> set[str]:
    """Valores fuente de un campo QC, sin inventar un valor para mezclas.

    ``size_declared`` es el mapeo existente de Size. Si también existe una columna
    ``size`` explícita, ambas deben concordar; una celda alternativa vacía no
    invalida un dato disponible, pero dos valores diferentes exigen inspector.
    """
    values: set[str] = set()
    for record in records:
        candidates = {
            record.get(source, "").strip()
            for source in QC_GENERAL_SOURCES[name]
            if record.get(source, "").strip()
        }
        values.update(candidates or {""})
    return values


def _qc_prefill(records: list[dict[str, str]], pallet_id: str) -> dict[str, str]:
    fields = {"pallet_id": pallet_id}
    for name in ("label_brand", "packing_date", "size", *OPTIONAL_GENERAL_FIELDS):
        if name in OPTIONAL_GENERAL_FIELDS and not any(name in record for record in records):
            continue
        values = _qc_values(records, name)
        fields[name] = next(iter(values)) if len(values) == 1 else ""
    return fields


def _header_prefill(records: list[dict[str, str]], lot_id: str) -> dict[str, str]:
    header = {"lot_id": lot_id}
    for name in HEADER_SOURCE_FIELDS:
        value = _unambiguous(records, name)
        if value:
            header[name] = value
    return header


def _validated_records(records: Any) -> list[dict[str, str]]:
    if not isinstance(records, list):
        raise ValueError("Los registros de recepción deben ser una lista de objetos CSV")
    validated: list[dict[str, str]] = []
    for row_number, record in enumerate(records, start=1):
        _validate_record(record, row_number)
        validated.append(dict(record))
    return validated


def manifest_summary(records: list[dict[str, str]]) -> dict[str, Any]:
    """Devuelve las filas y resume entidades sin convertir el manifest en QC.

    Las filas idénticas se preservan para trazabilidad, tanto en el resumen de
    filas como al resolver una paleta. ``pallets_count`` cuenta combinaciones
    únicas de embarque, lote y pallet, por lo que repetir una línea no lo aumenta.
    """
    validated = _validated_records(records)
    return {
        "records": deepcopy(validated),
        "lot_ids": sorted({record["lot_id"].strip() for record in validated}),
        "pallets_count": len({_group_key(record) for record in validated}),
    }


def resolve_reception(
    records: list[dict[str, str]],
    scan_input: str | int,
    lot_id: str | int | None = None,
) -> dict[str, Any]:
    """Busca coincidencias exactas de ``scan_code`` o ``pallet_id``.

    La selección corresponde a una combinación única de lote, pallet y embarque.
    Incluye todas sus líneas para conservar paletas con varios calibres. Un código
    que identifica varias combinaciones requiere contexto en vez de una elección
    silenciosa. No interpreta prefijos ni fabrica una recepción ausente.
    Las líneas idénticas se conservan como fuente, sin sumar mediciones QC.
    """
    scan = _identifier(scan_input, "scan_input")
    lot = _identifier(lot_id, "lot_id") if lot_id is not None else None
    validated = _validated_records(records)

    matches = [
        record
        for record in validated
        if scan in {record["scan_code"].strip(), record["pallet_id"].strip()}
        and (lot is None or record["lot_id"].strip() == lot)
    ]
    groups = {_group_key(record) for record in matches}
    if not groups:
        raise ValueError(f"Paleta no encontrada para el código '{scan}' en el manifest")
    if len(groups) != 1:
        raise ValueError(
            f"El código '{scan}' es ambiguo entre lotes, paletas o embarques; "
            "se requiere contexto de recepción"
        )
    selected_group = next(iter(groups))
    selected = [deepcopy(record) for record in validated if _group_key(record) == selected_group]
    return {
        "scan_input": scan,
        "lot_id": selected_group[0],
        "pallet_id": selected_group[1],
        "records": selected,
        "qc_header": _header_prefill(selected, selected_group[0]),
        "qc_fields": _qc_prefill(selected, selected_group[1]),
    }


def resolve_reception_lot(
    records: list[dict[str, str]],
    scan_input: str | int | None = None,
    lot_id: str | int | None = None,
) -> dict[str, Any]:
    """Abre un lote por selección explícita o escaneando una de sus paletas.

    Sin ``scan_input``, exige un ``lot_id`` existente y no inventa un escaneo.
    La selección de cada paleta reutiliza la consulta exacta existente.
    No se agregan otros lotes ni se elige un embarque ambiguo silenciosamente.
    Las paletas se devuelven en el orden de aparición de la fuente; líneas de
    calibres distintos o repetidas siguen en la procedencia de cada paleta.

    ``inspector_required`` enumera campos generales con valores contradictorios
    o diferentes entre líneas de una paleta. Los datos desconocidos siguen
    vacíos, y no se generan Sample, Pulp, defectos ni mediciones a partir de las
    cantidades esperadas. ``records`` conserva el roster completo del lote para
    que la aplicación pueda guardar y comprobar el alcance de la inspección.
    """
    validated = _validated_records(records)
    anchor = None
    if scan_input in (None, ""):
        if lot_id is None:
            raise ValueError("Seleccionar un lote o escanear una paleta del manifiesto.")
        selected_lot = _identifier(lot_id, "lot_id")
    else:
        anchor = resolve_reception(validated, scan_input, lot_id)
        selected_lot = anchor["lot_id"]
    lot_records = [record for record in validated if record["lot_id"].strip() == selected_lot]
    if not lot_records:
        raise ValueError(f"Lote no encontrado para el código '{selected_lot}' en el manifest")
    pallet_ids = list(dict.fromkeys(record["pallet_id"].strip() for record in lot_records))
    pallets = []
    inspector_required = []
    for pallet_id in pallet_ids:
        # Resolver contra todas las filas del lote detecta IDs de paleta
        # reutilizados entre embarques y colisiones de scan_code/pallet_id.
        selection = resolve_reception(lot_records, pallet_id, selected_lot)
        if anchor is not None and pallet_id == anchor["pallet_id"]:
            selection["scan_input"] = anchor["scan_input"]
        pallets.append(selection)
        mixed_fields = [
            name for name in QC_GENERAL_SOURCES if len(_qc_values(selection["records"], name)) > 1
        ]
        if mixed_fields:
            inspector_required.append({"pallet_id": pallet_id, "fields": mixed_fields})
    return {
        "lot_id": selected_lot,
        "selection_mode": "scan" if anchor is not None else "lot",
        "scanned_pallet_id": anchor["pallet_id"] if anchor is not None else None,
        **({"scan_input": anchor["scan_input"]} if anchor is not None else {}),
        "qc_header": _header_prefill(lot_records, selected_lot),
        "records": deepcopy(lot_records),
        "pallets": pallets,
        "inspector_required": inspector_required,
    }
