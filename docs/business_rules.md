# Business Severity existente

Fuentes: `smartfruit_integration_v1.py`, bloque Business Severity del notebook Predictive v4 e imagen de criterios proporcionada. Este documento describe reglas existentes; no incorpora nuevos thresholds.

El [contexto de Level Flag aportado por el usuario](level_flag_context.md) registra la tabla de severidad comunicada, los triggers operativos y la confirmación final de QC. Explicita las diferencias con la política `higher` y con los máximos por grupo implementados aquí; su incorporación es documental.

| Clave existente | Nombre de negocio en el código | Grupo | Familia |
|---|---|---|---|
| `scars_pct` | Cicatrices / defectos de piel | quality | `quality_5_20` |
| `blanching_pct` | Blanqueamiento / decoloración | quality | `quality_5_20` |
| `yellow_color_pct` | Color amarillo / sobremaduro | quality | `quality_5_20` |
| `oleocellosis_pct` | Oleocelosis | condition | `condition_5_10` |
| `styler_pct` | Styler (limes) | condition | `condition_5_10` |
| `skin_breakdown_pct` | Skin Breakdown / Fumigation Damage | condition | `skin_breakdown_0_5` |
| `mold_pct` | Moho | condition | `mold_decay_0_1` |
| `decay_pct` | Pudrición | condition | `mold_decay_0_1` |

## Comportamiento de la integración con `boundary_policy='higher'`

Porcentajes en escala 0–100.

| Familia | Nivel 1 | Nivel 2 | Nivel 3 |
|---|---|---|---|
| `quality_5_20` | 0 ≤ x < 5 | 5 ≤ x < 20 | x ≥ 20 |
| `condition_5_10` | 0 ≤ x < 5 | 5 ≤ x < 10 | x ≥ 10 |
| `skin_breakdown_0_5` | x = 0 | 0 < x < 5 | x ≥ 5 |
| `mold_decay_0_1` | x = 0 | 0 < x < 1 | x ≥ 1 |

El notebook explica que la imagen no fija inequívocamente las fronteras exactas. Tanto el notebook como la integración ofrecen `higher` (igualdad al nivel superior) y `lower` (igualdad al nivel inferior). La demo usa `higher`. Se conservará de forma explícita y trazable; su aprobación operativa por QC sigue pendiente. No elegir silenciosamente otra política.

`evaluate_business_severity` conserva el nivel máximo entre los ocho defectos. Desde la validación QC del 18/11/2026, la primera caja mapea 1 → STANDARD y 2/3 → EXTEND. La segunda caja completada produce COMPLETE y no permite una tercera. Los motivos son los defectos que alcanzan el máximo cuando es mayor que 1. Level 3 y el Level Flag humano se conservan; no se convierten en decisiones comerciales del inspector. La versión de reglas queda en el reporte.

La dominancia `Decay > Styler > Yellow Color > defectos superficiales` procede de `QC user validation 2026-11-18`, no de la matriz histórica. `defect_dominance.py` solo la aplica a etiquetas de un mismo fruto explícitamente identificado. Los conteos agregados independientes permanecen intactos.

El notebook también construye sumas y conteos de severidad para experimentos predictivos. Esas features no constituyen nuevos thresholds operativos para recomendar.

## Cobertura pendiente

El Excel registra además Soft, Wounds, Int. Dryness, Black tips, Skin defect, White stain, Stain y Undersize. No están en `BUSINESS_DEFECT_MAP`. La imagen aporta criterios adicionales y posibles equivalencias, pero hay que documentar los mapeos y resolver los términos ambiguos antes de aplicarlos. Registrar esos datos manualmente no autoriza inventar sus reglas ni ignorarlos como si fueran cero.

Un resultado calculado solo con los ocho defectos no debe presentarse como evaluación completa de los dieciséis. La política operativa para finalizar una inspección con defectos sin regla es un pendiente explícito, no una regla creada aquí.
