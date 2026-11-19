# EXTEND: revisar una caja adicional de una paleta

Flujo solicitado por el usuario el **15 de noviembre de 2026**. Después de ver los resultados y la sugerencia de SmartFruit, el inspector puede actualizar el estado de esa paleta. Si elige **EXTEND**, puede inspeccionar otra caja, cargar sus JSON de Vision y sumar sus cantidades a la misma paleta, conservando el detalle de cada revisión.

## Decidir junto a la sugerencia

En **Revisión y reporte**, cada paleta muestra sus resultados y la sugerencia del sistema. El inspector elige **STANDARD** o **EXTEND** después de evaluar la primera caja. Después de la segunda queda **COMPLETE**. El estado es provisional hasta confirmar el reporte.

El motor utiliza **EXTEND** para los niveles 2 y 3 y conserva `EXPAND` como alias de entrada histórica. Los thresholds y el Level Flag oficial del lote permanecen separados: el inspector sigue registrando ese Flag.

## Agregar la revisión de otra caja

1. Evalúa la inspección inicial y revisa la sugerencia de la paleta.
2. En esa misma paleta, selecciona **EXTEND**. Se habilita **EXTEND · revisar otra caja**.
3. Carga uno o varios **JSON de Vision de la caja adicional**. Deben corresponder a esa paleta y contener fotografías distintas de las utilizadas anteriormente.
4. Ajusta los checks de oleocelosis de la caja adicional: todos aparecen marcados inicialmente; desmarca los falsos positivos. Registra el revisor una vez y confirma el conjunto con **Aplicar selección** para JSON importados o **Incorporar fotos** para resultados procesados. **Sample se calcula a partir de los JSON únicos** y oleocelosis usa solo los incluidos y confirmados por QC. Registra los **quince defectos manuales de esa caja**, sin repetir las cantidades de la primera revisión.
5. Si ya comprobaste que los defectos todavía vacíos están ausentes, puedes usar **Registrar pendientes de esta caja en 0**. Los vacíos no se convierten automáticamente en cero y las cantidades ya registradas se conservan.
6. Añade observaciones de esta revisión.
7. Pulsa **Agregar caja y actualizar resultados**. La aplicación valida toda la revisión antes de incorporar sus datos.
8. Revisa el acumulado y el historial. La segunda caja cierra la ampliación con **COMPLETE**, conservando la severidad y evidencia.

Las otras paletas conservan sus cantidades y estados provisionales. La confirmación del reporte vuelve a estar pendiente. El máximo es **dos cajas por paleta**; el servidor rechaza revisiones adicionales posteriores.

La demo permite simular la revisión adicional con otro JSON válido disponible. Un archivo ya utilizado no se vuelve a contar como una caja nueva: se debe elegir una fotografía con otro `image_id` y verificar que represente frutos distintos.

Para probar se incluye [DEMO_ADDITIONAL_BOX_001.json](../examples/vision/DEMO_ADDITIONAL_BOX_001.json): **12 frutos ficticios y 2 sospechas**, identificado como `SIMULATED_DEMO`. Si QC mantiene marcados y confirma los cinco positivos entre ambas cajas, el acumulado es **48 frutos y 5 con oleocelosis (10,4167%)**. Desmarcar sospechas reduce el conteo operativo una vez aplicada la selección. Es una simulación técnica y no corresponde a una caja comercial.

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
