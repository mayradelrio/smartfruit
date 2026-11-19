# Contrato actual de Vision

Fuente: los 214 JSON del ZIP adjunto. Se conservarán nombres, clases y estructura.

| Campo principal | Contenido observado |
|---|---|
| `image_id` | Identificador de fotografía |
| `partition` | `train`, `val` o `test`; partición de evaluación, no identificación comercial |
| `total_fruits` | Cantidad de frutos evaluados en esa fotografía |
| `oleocellosis_count` | Cantidad clasificada con oleocelosis |
| `oleocellosis_pct` | Porcentaje sobre `total_fruits`, escala 0–100 |
| `mean_confidence` | Confianza media de la fotografía |
| `fruit_predictions` | Lista de predicciones por fruto/crop |

Cada elemento de `fruit_predictions` contiene `crop_id`, `predicted_class`, `oleocellosis_probability` y `confidence`. Las clases observadas son `con_oleocelosis` y `sin_oleocelosis`. Probabilidad y confianza se expresan en escala 0–1.

No contiene `lot_id`, `pallet_id` ni `sample_id`; esos identificadores ya existen en la integración y deben asociarse fuera del JSON de Vision mediante el flujo de inspección.

## Vinculación con la muestra y el QC Report

El escaneo resuelve la paleta en el manifiesto y establece lote/paleta antes de iniciar QC. La aplicación crea la muestra bajo ese contexto y adjunta los JSON a `samples[].vision_records`. La asociación queda en la captura de SmartFruit y no agrega campos al output del modelo.

El Excel obtiene `AgroPeru Lot Number` de `qc_header.lot_id`, `N° PALLET` de `qc_fields.pallet_id` y los conteos de `Sample`/`Oleocellosis` de la agregación de esa muestra. El resto de campos QC se conserva desde recepción o la captura manual del inspector, según corresponda.

La importación de JSON históricos conserva la asignación explícita del inspector a la muestra abierta. Un JSON histórico sin asociación previa no demuestra por sí mismo de qué lote o paleta procede. La app local ofrece además [inferencia desde fotografías](../vision_capture.md): el trabajo registra lote, paleta y muestra antes de ejecutar el modelo y devuelve los JSON bajo ese mismo contexto. El inspector confirma los resultados antes de incorporarlos a la captura; EXTEND permite preparar otra revisión para esa paleta.

La validación actual rechaza una recepción cuyo lote/paleta no coincide con la muestra y una fotografía asignada a varias muestras dentro del mismo reporte. Estas comprobaciones no permiten deducir automáticamente la procedencia física de fotografías antiguas sin registro.

`POST /api/vision/import` recibe la cabecera QC, todas las muestras actuales, el `sample_id` de destino y los `vision_records` entrantes. Valida el conjunto antes de incorporarlo, aun con la captura QC incompleta. Devuelve los registros originales, el resumen de agregación y `image_bindings`: una asociación externa por imagen única con `image_id`, `sample_id`, `pallet_id` y `lot_id`. Estos cuatro nombres ya existen en el proyecto; el contenedor de asociaciones es una extensión de SmartFruit y no pertenece al JSON Vision.

Un duplicado idéntico se conserva en los registros para trazabilidad, pero no aumenta los conteos ni duplica su asociación. Se rechazan contenido distinto bajo el mismo `image_id`, imágenes de otra muestra y asociaciones que no correspondan al contexto. La captura y el reporte final conservan `image_bindings`; las entradas anteriores sin este campo siguen siendo compatibles. La unicidad se comprueba dentro de una inspección, sin un registro global entre reportes.

## Agregación existente

`aggregate_vision_sample` suma `total_fruits` de imágenes únicas y cuenta únicamente los positivos confirmados por QC. El campo original `oleocellosis_count` de cada JSON sigue siendo la salida cruda del modelo. La agregación informa `suspected_oleocellosis_count`, `confirmed_oleocellosis_count`, `pending_review_count` y la auditoría `vision_review`. El porcentaje operativo es `100 * confirmados / suma_frutos`; no se promedian porcentajes de imágenes. La confianza se conserva para auditoría y no representa exactitud.

Desde el 18/11/2026 cada predicción puede incluir `review_status` (pending/confirmed/rejected), `reviewed_by`, `reviewed_at`, `override_label` y `override_reason`. Un positivo sin esos campos queda pendiente. Confirmar o rechazar exige revisor y fecha; un rechazo conserva clase/probabilidad originales y su corrección humana. Las etiquetas styler/scar/inking/clean/other no alimentan automáticamente defectos manuales. La evaluación se bloquea hasta revisar todos los positivos. Ver [segunda prueba de usuario](../user_feedback_v2.md).

La interfaz usa un check por positivo, marcado inicialmente salvo que ya exista un rechazo guardado. `qc_included`, booleano opcional por predicción, conserva esa selección: `true` incluye y `false` excluye. Este campo por sí solo no confirma una detección. QC confirma el conjunto con un solo revisor y fecha mediante **Aplicar selección** o **Incorporar fotos**; los incluidos pasan a confirmed y los excluidos a rejected. Cambiar un check deja esa detección pendiente hasta aplicar de nuevo la selección. Una exclusión sin motivo específico usa `override_label: "other"` y `override_reason: "Excluido por QC mediante el check de oleocelosis."`, conservando los datos originales del modelo.

La integración produce `vision_summary` con `images_processed`, `image_ids`, `total_fruits`, `oleocellosis_count`, `oleocellosis_pct`, `mean_confidence`, `low_confidence_threshold`, `low_confidence_count`, `low_confidence_items` y `duplicate_image_ids_ignored`.

Los resultados generados incluyen metadatos `inference` con el nombre de origen y el tipo de entrada. El catálogo identifica copias del mismo archivo por su contenido. La validación también impide combinar el JSON histórico de una foto completa con los nuevos resultados de sus recortes, tanto dentro de una muestra como entre paletas o revisiones. Recortes distintos de una misma foto sí se pueden sumar. Estas comprobaciones no identifican frutos repetidos en fotografías distintas sin identidad compartida.

La referencia usa `low_confidence_threshold=0.70`, solo para trazabilidad: no es un umbral nuevo de severidad ni debe generar recomendaciones por sí mismo.

## Validación del MVP

El código original valida campos mínimos, longitud de predicciones y porcentaje con tolerancia 0,02. El MVP conserva esa tolerancia y valida también dominio y tipos, clases y cantidades, valores finitos, campos del contrato actual y conflictos entre registros con el mismo `image_id`, sin cambiar el output del modelo. No redondea el porcentaje agregado antes de aplicar las reglas; el redondeo se usa solo para presentación.

Para fotografías de los mismos frutos desde varios ángulos, el contrato actual no ofrece una identidad global del fruto. No se puede prometer deduplicación de frutos entre imágenes.
