"""QC's operational priority, separate from the historical threshold matrix.

This applies to labels explicitly assigned to one fruit. Aggregate manual counts
are independent observations and must never be deduplicated with this rule.
"""

DEFECT_DOMINANCE = ["decay", "styler", "yellow_color", "surface_defects"]
DOMINANCE_METADATA = {
    "version": "1.0.0",
    "source": "QC user validation 2026-11-18",
    "status": "stakeholder-validated",
    "limitation": "No existe identificación por fruto para todos los 16 defectos.",
}
SURFACE_DEFECTS = frozenset({"oleocellosis", "skin_breakdown", "scar", "scars"})


def primary_defect(fruit_id, labels):
    """Resolve only documented priorities for labels on an identified fruit.

    Surface defects are tied: no ordering within that group was validated.
    Unknown labels and ties stay unresolved instead of inventing priorities.
    """
    if not isinstance(fruit_id, str) or not fruit_id.strip():
        raise ValueError("La dominancia requiere identificar explícitamente el mismo fruto.")
    if not isinstance(labels, (list, tuple, set, frozenset)) or not labels:
        raise ValueError("Registrar las etiquetas observadas en el mismo fruto.")
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("Cada etiqueta de defecto debe ser texto.")
    labels = set(labels)
    labels = {"yellow_color" if label == "yellow" else label for label in labels}
    known = {"decay", "styler", "yellow_color", *SURFACE_DEFECTS}
    if labels - known:
        return None
    for name in DEFECT_DOMINANCE[:3]:
        if name in labels:
            return name
    return next(iter(labels)) if len(labels) == 1 else None
