# EXTEND: revisar una caja adicional de una paleta

Flujo solicitado por el usuario el **15 de noviembre de 2026**. Después de ver los resultados y la sugerencia de SmartFruit, el inspector puede actualizar el estado de esa paleta. Si elige **EXTEND**, puede inspeccionar otra caja, cargar sus JSON de Vision y sumar sus cantidades a la misma paleta, conservando el detalle de cada revisión.

## Decidir junto a la sugerencia

En **Revisión y reporte**, cada paleta muestra sus resultados, la sugerencia del sistema y el control **Actualizar estado de esta paleta**. El inspector puede elegir **STANDARD**, **EXTEND** o **ESCALATE**. Su estado es provisional hasta confirmar el reporte; la selección no modifica ni sustituye la sugerencia calculada.

La web utiliza **EXTEND** para ampliar la inspección. El motor existente conserva el valor técnico `EXPAND`; ambos identifican la misma acción. No se cambian las reglas de Business Severity ni se deduce automáticamente el Level Flag oficial del lote. El inspector sigue registrando ese Flag.

## Agregar la revisión de otra caja

1. Evalúa la inspección inicial y revisa la sugerencia de la paleta.
2. En esa misma paleta, selecciona **EXTEND**. Se habilita **EXTEND · revisar otra caja**.
3. Carga uno o varios **JSON de Vision de la caja adicional**. Deben corresponder a esa paleta y contener fotografías distintas de las utilizadas anteriormente.
4. Revisa los frutos y la oleocelosis detectados en la caja adicional. **Sample se calcula automáticamente a partir de los JSON únicos cargados**, sin seleccionar ni confirmar manualmente su cobertura. Registra únicamente los **quince defectos manuales de esa caja**, sin volver a escribir las cantidades de la primera revisión.
5. Si ya comprobaste que los defectos todavía vacíos están ausentes, puedes usar **Registrar pendientes de esta caja en 0**. Los vacíos no se convierten automáticamente en cero y las cantidades ya registradas se conservan.
6. Añade observaciones de esta revisión.
7. Pulsa **Agregar caja y actualizar resultados**. La aplicación valida toda la revisión antes de incorporar sus datos.
8. Revisa el nuevo acumulado, el historial y la nueva sugerencia. El estado de la paleta ampliada vuelve a pendiente para que el inspector decida otra vez sobre los resultados actualizados.

Las otras paletas conservan sus cantidades y estados provisionales. La confirmación del reporte vuelve a estar pendiente. Se pueden agregar más cajas repitiendo el mismo flujo con nuevos JSON y nuevas cantidades observadas.

La demo permite simular la revisión adicional con otro JSON válido disponible. Un archivo ya utilizado no se vuelve a contar como una caja nueva: se debe elegir una fotografía con otro `image_id` y verificar que represente frutos distintos.

Para probar sin preparar un archivo nuevo, se incluye [DEMO_ADDITIONAL_BOX_001.json](../examples/vision/DEMO_ADDITIONAL_BOX_001.json): **12 frutos ficticios, 2 con oleocelosis**, identificado explícitamente como `SIMULATED_DEMO`. Se puede seleccionar como caja adicional después de **Cargar demo técnica**. El acumulado pasa de 36 frutos y 3 con oleocelosis a **48 frutos y 5 con oleocelosis (10,4167%)**. Es una simulación técnica; no corresponde a una caja comercial ni a una inferencia nueva del modelo.

## Cómo se suman los resultados

Cada cantidad se acumula en la paleta de destino:

```text
Sample acumulado = Sample inicial + Sample de las cajas adicionales
Defecto acumulado = defecto inicial + defecto de las cajas adicionales
Porcentaje acumulado = 100 × defecto acumulado / Sample acumulado
```

Los porcentajes se calculan sobre el total real de frutos; no se promedian los porcentajes de las cajas. Vision aporta Sample y Oleocellosis de la caja adicional. Los otros defectos proceden de las cantidades manuales explícitas del inspector.

Ejemplo:

| Revisión | Sample | Frutos con oleocelosis | Oleocelosis | Scars |
| --- | ---: | ---: | ---: | ---: |
| Inicial | 12 | 1 | 8,33% | 2 |
| Caja adicional | 24 | 6 | 25,00% | 1 |
| Acumulado de la paleta | 36 | 7 | 19,44% | 3 |

La fila principal QC sigue siendo **una fila por paleta**, con las cantidades acumuladas. El historial conserva la primera revisión y cada caja adicional por separado. Cuando Reason utiliza el resumen calculado de defectos, se actualiza con el nuevo acumulado; si el inspector ajustó su redacción, debe contrastarla con el resumen actualizado antes de confirmar.

## Historial y reportes

La web, el Excel y la vista imprimible muestran por paleta:

- La inspección inicial y sus cantidades.
- Cada revisión adicional, su Sample, oleocelosis, otros defectos e imágenes.
- La acción EXTEND que amplió la inspección, las sugerencias anterior y posterior y las observaciones de la revisión.
- El acumulado y sus porcentajes recalculados.

El registro JSON conserva también los JSON originales de Vision y el historial estructurado. La salida original del modelo se preserva; lote, paleta, estado e historial son datos de la aplicación que la acompañan.

Las mediciones ya incorporadas se conservan en sus revisiones. Los conteos acumulados y las fotografías de una paleta con historial se modifican mediante la acción de revisión adicional, evitando reescribir el total directamente o importar otra caja por la carga inicial de Vision. El inspector puede seguir corrigiendo los datos generales y completando los campos finales sin alterar las mediciones históricas.

## Contrato de la aplicación

`POST /api/inspection/additional-review/preview` valida los JSON propuestos y su asociación a la muestra antes de sumarlos. Recibe la captura actual, `sample_id` de destino y los nuevos `vision_records` en el nivel superior. No incorpora cantidades ni guarda la revisión.

`POST /api/inspection/additional-review` recibe la captura actual y estos campos adicionales:

```text
sample_id: identificador de la muestra de la paleta de destino
inspector_decision: EXPAND o EXTEND
additional_review:
  vision_records: JSON originales de la caja adicional
  manual_defects: las quince cantidades manuales adicionales
  observations: observaciones de esta revisión
```

Devuelve `capture` con los datos actualizados, `report` recalculado y `review` con la revisión incorporada. La UI solo aplica esta respuesta cuando la operación completa tiene éxito. Una validación fallida conserva las cantidades y archivos anteriores.

Cada muestra con revisiones adicionales conserva:

```text
review_history:
  initial:
    vision_records, qc_fields, inspection_summary, system_recommendation
  additional:
    - review_number, trigger_decision, vision_records, manual_defects,
      qc_fields, inspection_summary, observations,
      system_recommendation_before, system_recommendation_after
```

Los `qc_fields` e `inspection_summary` de cada entrada corresponden solo a esa revisión. Los campos principales de la muestra representan el acumulado. `review_choice` conserva el estado provisional del inspector y se mantiene separado de la decisión final confirmada.

El servidor reconstruye el historial desde los JSON originales y las cantidades manuales explícitas: comprueba la secuencia de revisiones, fotografías no reutilizadas y correspondencia de las sumas con el acumulado. Los porcentajes y las sugerencias se recalculan con las reglas vigentes; no se aceptan como totales independientes suministrados por el cliente. Se rechazan JSON inválidos, imágenes repetidas entre revisiones o paletas, cantidades ausentes o fuera de rango y acumulados incompatibles con el historial.

Ver también [flujo por lote](lot_workflow.md) y [contexto de Level Flag y Reason](level_flag_context.md).
