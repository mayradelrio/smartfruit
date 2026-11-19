"""Private, persistent Vision process; one NDJSON reply per stdin request.

The inference module is imported once. Its model caches survive between jobs;
status checks still load neither Torch nor model weights. The existing one-shot
``smartfruit.vision_inference`` CLI remains available independently.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

from .local_files import write_json_atomic
from .vision_inference import get_runtime_status, run_request


def _dispatch(message):
    operation = message.get("op")
    if operation == "status":
        return get_runtime_status(message.get("models_dir"), message.get("input_kind", "fruit_crop"))
    if operation != "infer":
        raise ValueError("Operación del worker Vision no reconocida.")
    request_path, output_path = message.get("request_path"), message.get("output_path")
    if not isinstance(request_path, str) or not isinstance(output_path, str):
        raise ValueError("La inferencia requiere request_path y output_path.")
    request = json.loads(Path(request_path).read_text("utf-8-sig"))
    if not isinstance(request, dict):
        raise ValueError("La solicitud de Vision debe ser un objeto JSON.")
    result = run_request(request)
    write_json_atomic(output_path, result)
    return {"output_path": output_path, "records_processed": len(result["records"])}


def main():
    # Keep a duplicate of the protocol pipe before redirecting fd 1. This also
    # moves native-library stdout writes to stderr, not just Python print().
    protocol = sys.stdout
    duplicated = False
    try:
        original_fd = protocol.fileno()
        protocol = os.fdopen(os.dup(original_fd), "w", encoding="utf-8", buffering=1)
        os.dup2(sys.stderr.fileno(), original_fd)
        duplicated = True
    except (AttributeError, OSError, ValueError):
        pass
    try:
        with redirect_stdout(sys.stderr):
            for line in sys.stdin:
                request_id = None
                try:
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError("El mensaje del worker debe ser un objeto JSON.")
                    request_id = message.get("id")
                    if not isinstance(request_id, str) or not request_id:
                        raise ValueError("El mensaje del worker requiere un identificador.")
                    result = _dispatch(message)
                    response = {"id": request_id, "ok": True, "result": result}
                except Exception as exc:
                    response = {"id": request_id, "ok": False, "error": str(exc)}
                protocol.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
                protocol.flush()
    finally:
        if duplicated:
            protocol.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
