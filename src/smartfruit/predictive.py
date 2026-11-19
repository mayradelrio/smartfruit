"""Adaptador opcional: OFF funciona sin cargar modelos o dependencias ML."""

import math
import os
from copy import deepcopy


def use_predictive_from_env():
    value = os.getenv("USE_PREDICTIVE", "False").strip().lower()
    if value not in ("true", "false"):
        raise ValueError("USE_PREDICTIVE debe ser False o True.")
    return value == "true"


def attach_predictive(record, enabled=False, provider=None):
    """Un provider existente puede aportar pérdida; no decide ni entrena.

    Sin artefacto/provider, ON queda no disponible y el flujo sigue por reglas.
    El adaptador es la única frontera de errores de una integración experimental.
    """
    result = deepcopy(record)
    signal = {"enabled": bool(enabled), "experimental": True, "decision": None}
    if enabled:
        signal["predicted_loss_pct"] = None
        if provider is None:
            signal["status"] = "unavailable"
            signal["reason"] = "No se ha conectado un artefacto Predictive existente."
        else:
            try:
                value = provider(deepcopy(record))
                if isinstance(value, dict):
                    value = value.get("predicted_loss_pct")
                if isinstance(value, bool) or value is None:
                    raise ValueError("Sin predicción numérica")
                prediction = float(value)
                if not math.isfinite(prediction) or not 0 <= prediction <= 100:
                    raise ValueError("Pérdida fuera de dominio")
                signal.update(predicted_loss_pct=prediction, status="available")
            except Exception:
                # No filtrar rutas, credenciales o traceback de un proveedor al reporte.
                signal["status"] = "unavailable"
                signal["reason"] = "Predictive no disponible; se conserva la evaluación por reglas."
    result["predictive"] = signal
    return result
