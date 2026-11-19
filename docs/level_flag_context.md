# Contexto de negocio: Business Severity y Level Flag de QC

Contexto aportado por el usuario el **14 de noviembre de 2026**, conservado para futuras decisiones de implementación. Este documento registra los criterios comunicados y sus diferencias con la aplicación actual. Su incorporación es documental; el comportamiento implementado se describe en [business_rules.md](business_rules.md) y [lot_workflow.md](lot_workflow.md).

## Dos resultados distintos

- **Business Severity v4:** severidad calculada por defecto y contexto para una recomendación SmartFruit. Debe mostrar los motivos y las reglas disparadas.
- **Level Flag oficial del QC Report:** juicio final editable y confirmado por el inspector. Se conserva en `qc_header.Level_Flag`; en el flujo actual, `level_flag_status` permanece en `INSPECTOR_REQUIRED` y se exige completar el campo antes de confirmar un lote nuevo.

No se ha establecido una regla oficial `Level_Flag = max(severidades)`, ni una equivalencia por promedio o suma. Las acciones operativas dependen también del defecto, su cantidad, las excepciones y las especificaciones vigentes. La recomendación SmartFruit acompaña la decisión de QC.

## Tabla de severidad comunicada

Los porcentajes están en escala 0–100. Las igualdades de esta tabla se conservan tal como las indicó el usuario.

| Regla / defecto | Level 1 | Level 2 | Level 3 |
| --- | --- | --- | --- |
| Oleocelosis | ≤ 5% | > 5% a 10% | > 10% |
| Styler | ≤ 5% | > 5% a 10% | > 10% |
| Quality agregado | ≤ 5% | > 5% a 20% | > 20% |
| Condition agregado | ≤ 5% | > 5% a 10% | > 10% |
| Skin Breakdown | 0% | > 0% a 5% | > 5% |
| Mold / Decay | 0% | > 0% a 1% | > 1% |

El extremo superior de cada intervalo de Level 2 está incluido. Para oleocelosis, superar 5% saca de Level 1 y superar 10% corresponde a Level 3.

### Diferencias con la aplicación actual

La tabla comunicada corresponde a la política de fronteras `lower` disponible en el código. La demo y la API usan actualmente `boundary_policy="higher"`: una igualdad con el umbral pasa al nivel superior. Por ejemplo:

| Caso exacto | Tabla comunicada (`lower`) | Demo actual (`higher`) |
| --- | --- | --- |
| Oleocelosis o Styler: 5% | Level 1 | Level 2 |
| Oleocelosis o Styler: 10% | Level 2 | Level 3 |
| Familia Quality: 20% | Level 2 | Level 3 |
| Skin Breakdown: 5% | Level 2 | Level 3 |
| Mold o Decay: 1% | Level 2 | Level 3 |

Esta diferencia queda registrada para resolverla al implementar el criterio comunicado. Guardar este contexto no cambia la política activa.

El motor actual evalúa ocho defectos individuales; Mold y Decay se evalúan por separado. `quality_max_level` y `condition_max_level` son máximos de los niveles individuales de cada grupo. No representan niveles calculados a partir de porcentajes agregados de Quality o Condition. Para implementar esos agregados falta precisar sus componentes, población y tratamiento de frutos con varios defectos; no se debe deducir esa fórmula de los nombres de los campos. Tampoco se ha definido una nueva política de recomendación para todo el lote.

## Porcentajes y triggers operativos

Para expresar un defecto como porcentaje:

```text
defect_pct = 100 * defect_count / actual_count
```

`actual_count` es la cantidad real de frutos de la población evaluada. El numerador y el denominador deben corresponder a esa misma población. El size/count esperado de recepción es una referencia declarada; el porcentaje usa la medición real. Si falta el denominador o vale cero, el porcentaje queda pendiente de resolución; los datos ausentes no se convierten en cero.

El usuario indicó estos triggers, separados de los intervalos de severidad:

- **Un fruto con decay impide Level 1** en el criterio de decay, porque exige cero decay.
- **Cuatro o más frutos con decay → segundo conteo / ampliar revisión.** Este trigger depende del conteo bruto y no reemplaza el cálculo del porcentaje.
- **Desviación del count real frente al size/count esperado → revisión.** El criterio comunicado exige revisar la diferencia y decidir si se inspecciona otra caja; no establece un porcentaje universal de tolerancia.

El segundo conteo por 4+ decay y la revisión por desviación de count no están implementados como triggers en la aplicación actual. Queda por precisar su alcance operativo —caja, muestra, paleta o lote— y las especificaciones aplicables antes de automatizarlos. No se debe inventar un umbral universal de desviación.

## Presentación prevista para QC

El flujo planteado por el usuario es:

1. Calcular la severidad de cada defecto con la regla y la política de fronteras identificadas.
2. Mostrar qué reglas dispararon los niveles y sus motivos (`Reason`).
3. Incorporar los triggers operativos adicionales cuando su alcance esté definido e implementado.
4. Generar una recomendación SmartFruit respetando las especificaciones y excepciones aplicables.
5. Permitir al inspector registrar, editar y confirmar el `Level Flag` oficial; conservar el valor confirmado y los motivos calculados.

La presentación debe separar el porcentaje medido, el nivel calculado, los motivos de la regla y la recomendación SmartFruit. El campo final de QC permanece pendiente hasta que el inspector lo registre y confirme; no se preselecciona a partir de la sugerencia.

Los motivos de Business Severity enumeran los defectos que alcanzan el máximo cuando es mayor que 1. Una explicación como `Oleocellosis > 5%` corresponde a la regla de severidad. El campo `generated_reason` contiene el resumen descriptivo de cantidades y porcentajes del lote.

### Aclaración del usuario: orden de revisión y origen de Reason

El **14 de noviembre de 2026**, el usuario precisó que el inspector debe decidir **después de ver los resultados de las paletas y la sugerencia del sistema**, y que **Reason proviene del resumen de defectos**. En la nueva captura, `qc_header.reason` se precarga con `generated_reason` después de evaluar; `reason_source: "defect_summary"` identifica esa procedencia. Si el inspector ajusta la redacción, pasa a `reason_source: "inspector"` y el resumen calculado sigue disponible por separado. El Reason del QC utiliza el resumen de defectos y conserva por separado la explicación de las reglas de severidad.

El inspector registra el Level Flag y las decisiones finales cuando los resultados ya están visibles. Esas elecciones no se preseleccionan a partir de las sugerencias. Editar el Level Flag o los campos finales de revisión conserva los cálculos y exige confirmar de nuevo. Cambiar los defectos o la evidencia de Vision sí exige una nueva evaluación y un resumen actualizado. Los borradores conservan `reason_source`, pero siguen retirando toda aprobación previa.

Las capturas anteriores sin `reason_source` mantienen su Reason registrado. Esta compatibilidad conserva las observaciones ya registradas; no las convierte en valores predeterminados del nuevo flujo ni reemplaza Remarks automáticamente.

El motor actual mapea la severidad máxima por muestra/paleta a `STANDARD`, `EXPAND` o `ESCALATE`. Este mapeo describe la recomendación SmartFruit implementada y no constituye una regla oficial de asignación de `Level_Flag`. El [contrato del QC Report](contracts/qc_report.md) mantiene separados el resultado calculado y el juicio final del inspector.

## Referencias y decisiones pendientes

Los criterios comunicados sobre umbrales, triggers operativos y asignación de Level Flag requieren cotejarse con las especificaciones vigentes del negocio antes de automatizar cambios. Los documentos de trabajo y sus versiones se conservan localmente; sus nombres y datos históricos no se distribuyen en esta documentación pública. Este registro no afirma haber revisado esas fuentes adicionales.
