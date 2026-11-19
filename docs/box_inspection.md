# Inspección de una caja completa

La captura distingue **caja física**, fotografías y acumulado de la paleta. Una caja puede necesitar muchas fotografías; el número de frutos de una imagen no representa por sí solo el contenido completo de la caja. Cada caja conserva su identificador y su comparación con los frutos declarados por caja del manifiesto.

## Capturar y finalizar

1. Abre la paleta desde el manifiesto y prepara la caja que vas a inspeccionar.
2. Divide físicamente sus frutos en grupos. Fotografía cada grupo una sola vez y evita que un fruto aparezca en dos grupos. La aplicación comprueba los identificadores de imagen repetidos; no reconoce un mismo fruto entre fotografías distintas.
3. Procesa y confirma las fotografías o incorpora varios JSON de Vision dentro de la misma caja. Puedes seguir añadiendo archivos mientras la captura está abierta.
4. Revisa el número de imágenes procesadas, los frutos detectados y el conteo esperado del manifiesto. Si la paleta tiene varias líneas con conteos distintos, selecciona la línea correspondiente a la caja.
5. Confirma expresamente que se han inspeccionado todos los frutos de esa caja y finaliza su captura. Alcanzar el conteo esperado no cierra la caja automáticamente.
6. Registra los demás defectos de esa misma población y evalúa la recomendación. Una diferencia entre conteo esperado y detectado queda visible para el inspector; no añade un nuevo umbral de severidad.

`Sample` sigue calculándose desde los resultados únicos de Vision. La confirmación de cobertura física indica que el inspector terminó la caja; no permite escribir un denominador distinto del detectado. Agregar o retirar evidencia exige revisar y finalizar nuevamente la captura antes de evaluar.

## Conteo esperado y detectado

El esperado procede de `expected_count_per_box` en la recepción vinculada. No se obtiene del número de cajas recibidas, del total de la paleta ni de `Avg. Count per Box.` del formulario QC.

```text
actual_count = suma de total_fruits de las imágenes únicas de la caja
count_difference = actual_count - expected_count_per_box
count_deviation_pct = 100 × count_difference / expected_count_per_box
missing_count = max(expected_count_per_box - actual_count, 0)
excess_count = max(actual_count - expected_count_per_box, 0)
```

Ejemplo: esperado 150, detectado 146, diferencia −4, desviación −2,67%, **4 unidades menos detectadas** y 0 unidades más detectadas. Es una comparación con la medición de Vision: por sí sola no demuestra un faltante comercial ni identifica su causa.

Un esperado ausente o declarado como cero deja el esperado y los cálculos dependientes en `null`, presentados como **No disponible**. Los valores declarados inválidos se rechazan. Si las líneas de recepción tienen conteos o tamaños incompatibles, la selección explícita resuelve qué declaración corresponde a la caja. No se elige un promedio ni se usa un tamaño distinto por inferencia.

La oleocelosis de la caja se calcula como `100 × sum(oleocellosis_count) / sum(total_fruits)`. No se promedian los porcentajes de las fotografías.

## Otra caja y acumulado de la paleta

Después de elegir **EXTEND**, la revisión adicional conserva su propia caja, imágenes, confirmación de cobertura y comparación de conteo. La primera caja no cambia su denominador al incorporar la segunda.

La fila principal del QC Report continúa siendo **una fila por paleta**, con los conteos y defectos acumulados. El detalle por caja del Excel y de la vista imprimible muestra cada esperado, detectado, diferencia, desviación y unidades menos/más detectadas por separado. El total acumulado de dos cajas no se compara contra el esperado de una sola caja. El historial inicial/adicional mantiene las cantidades originales de cada revisión.

El borrador del navegador también conserva una caja adicional todavía pendiente de incorporación: sus JSON originales, identificación, cierre de captura, cantidades manuales vacías o registradas y observaciones. Editar los datos iniciales retira la evaluación y las decisiones, pero conserva esa captura adicional. Al recuperar el borrador hay que evaluar de nuevo y elegir **EXTEND** para revisarla y continuar; el cierre físico de la caja no restaura una aprobación del reporte. Antes de confirmar el reporte se debe incorporar la caja pendiente o usar **Descartar caja adicional pendiente**, que conserva la inspección inicial y las ampliaciones ya incorporadas.

## Contrato

Las capturas nuevas incorporan esta metadata en cada muestra:

```json
{
  "box_inspection": {
    "sample_box_id": "BOX_001",
    "status": "completed",
    "coverage_confirmed": true,
    "manifest_record_index": null
  }
}
```

Durante la captura, `status` es `capturing` y `coverage_confirmed` es `false`. Para evaluar una captura nueva se requiere `completed` y cobertura confirmada. `manifest_record_index` es el índice desde cero de la línea seleccionada en `sample.reception.records`; puede permanecer `null` cuando no hace falta desambiguar la recepción.

El servidor recalcula los resultados desde Vision y recepción. El resumen de cada caja contiene:

```text
sample_box_id, status, coverage_confirmed, manifest_record_index, size_declared
images_processed, actual_count, expected_count_per_box
count_difference, count_deviation_pct, missing_count, excess_count
oleocellosis_count, oleocellosis_pct, comparison_status
```

`comparison_status` distingue `matched`, `shortage`, `excess` y `unavailable`; `selection_required` identifica la selección pendiente cuando hay declaraciones incompatibles.

En el reporte de una muestra, `box_inspection` representa la caja inicial y `box_inspections` contiene la lista de cajas. Cuando existe una ampliación, `review_history.initial.box_inspection` y cada `review_history.additional[].box_inspection` conservan sus propios resultados. `inspection_summary` y `qc_fields` principales continúan representando el acumulado de la paleta.

Las capturas antiguas sin esta metadata conservan su compatibilidad. Su ausencia no certifica que las fotografías correspondan a una caja física completa; los exportadores no les inventan una comparación por caja.
