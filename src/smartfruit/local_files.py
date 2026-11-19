"""Escrituras locales atómicas tolerantes a bloqueos breves de Windows/OneDrive."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


def write_json_atomic(path: str | Path, value: Any, *, indent: int | None = None) -> None:
    """Reemplaza un JSON completo; reintenta permisos transitorios hasta 10 veces.

    El temporal está en el mismo directorio para mantener el reemplazo atómico.
    Su nombre único evita interferencias entre procesos/escrituras simultáneas.
    """
    destination = Path(path)
    content = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=indent)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        for attempt in range(10):
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_text(content, encoding="utf-8")
                temporary.replace(destination)
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(min(0.15, 0.02 * (attempt + 1)))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # Un sincronizador podría mantener abierto incluso el temporal.
            pass
