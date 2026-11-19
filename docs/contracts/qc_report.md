# Contrato del QC Report

El reporte usa la hoja `Report` y las plantillas QC vacías distribuidas con el proyecto. Conserva la terminología del formato y la identidad AgroPeru autorizada, incluida la etiqueta `AgroPeru Lot Number`; la clave interna `lot_id` no cambia. Los reportes completados y sus valores de inspección permanecen fuera del repositorio.

## Cabecera y bloques

`Inspection Date`, `Vessel`, `Container`, `AgroPeru Lot Number`, `Country Of Origin`, `Remarks`, `Level Flag`, `Reason`, `Grade`, `Color` y `PLU%`.

En la plantilla vacía, la tabla de detalle tiene encabezados en fila 15 y bloques `General Information`, `Condition` y `Quality` en fila 14. La posición puede variar entre formatos de entrada; los importadores deben localizar las etiquetas de encabezado. El número de muestras es dinámico.

| Bloque | Columnas originales |
|---|---|
| General Information, A–I | Label; N° PALLET; Grower; Packing date; Size; Avg. Count per Box.; PLU (%); PLU/Coo; Sample |
| Condition, J–U | Open Rating; Color Rating; Pulp; Decay; Styler; Mold; Soft; Skin breakdown; Oleocellosis; Wounds; Int. Dryness; Black tips |
| Quality, V–AB | Skin defect; Scars; White stain; Blanching; Yellow color; Stain; Undersize |
| Total, AC | Total Percent of each sample |

Los dieciséis defectos de M–AB se registran como cantidades de frutos. `Sample` es el denominador de la fila. El total de cada muestra usa `SUM(M:AB)/Sample`; los porcentajes por columna dividen las cantidades acumuladas por el total de `Sample`. `Total Percent Combined` suma los porcentajes por defecto.

Estos totales expresan suma de incidencias de defectos; no prueban cuántos frutos únicos presentan cualquier defecto. No cambiar su significado ni imponer un límite conjunto de 100 % sin definición de QC.

## Vision y entrada manual

- Precargar cantidad de frutos evaluados por Vision, cantidad con oleocelosis y su porcentaje, conservando procedencia/confianza útil.
- Precargar `Oleocellosis` con la cantidad correspondiente a la muestra cubierta por Vision.
- Solo completar `Sample` con el total de Vision si ambas poblaciones coinciden. Si Vision cubre una parte, mantener diferenciados los denominadores y resolver el alcance antes de evaluar porcentajes comparables.
- Mantener entrada manual de los demás defectos y datos. Un dato pendiente no equivale a cero.
- Conservar los campos existentes; cualquier dato adicional de trazabilidad será una ampliación documentada, no una modificación del contrato Vision.

## Sección SmartFruit solicitada

Al final: nivel/severidad resultante; STANDARD / EXPAND / ESCALATE; motivo; Predictive OFF / ON - Experimental; `predicted_loss_pct` solo con ON; confirmación/decisión final del inspector; observaciones.

No sobrescribir `Level Flag`, `Grade`, `Remarks` ni otros juicios del inspector con resultados calculados. La severidad calculada por defecto y el Level Flag final son campos con responsabilidades distintas. No hay una regla oficial que permita deducir el Flag del máximo, la suma o el promedio de severidades.

## Calidad de datos fuente

Los archivos de entrada pueden usar distintas escalas o formatos para PLU (%) y Pulp. Conservar el valor registrado y confirmar su unidad antes de normalizarlo; no corregir mediciones por suposición.

Una paleta puede contener tamaños mezclados; el texto registrado en `Avg. Count per Box.` y las líneas de recepción deben conservar esa distinción. La clasificación de compra y el país de origen son datos independientes. Las reglas de recepción se documentan en [recepción](../reception.md).

La exportación conserva la estructura original y agrega SmartFruit. Las pruebas comparan datos, fórmulas, estilos y geometría contra las referencias; su alcance está en [fidelidad del Excel](../qc_fidelity.md). La actualización actual se verificó con Python y Node/Pyodide, sin prueba de navegador publicado ni de paginación en Excel.

## Contenedor digital de la aplicación

El nuevo reporte QC usa `schema_version: "1.1"`. Esta versión corresponde al contenedor del reporte y no modifica el JSON de Vision. Conserva `lot_id` y agrupa `qc_header` y `samples`.

- `qc_header` utiliza los nombres del parser existente donde estaban definidos (`inspection_date`, `lot_id`, `country_origin`, `Level_Flag`, `plu_pct`); las demás etiquetas de cabecera se representan como `vessel`, `container`, `remarks`, `reason`, `grade` y `color`.
- Cada elemento de `samples` conserva los campos de la salida de integración v1: identificadores, `inspection_summary`, `defects`, `business_severity`, `predictive`, `final_recommendation`, `recommendation_reasons`, `human_confirmation_required` e `inspector_final_decision`.
- `qc_fields` conserva las cantidades y datos de fila con los nombres del parser del notebook. `rule_coverage` declara `evaluated` y `not_evaluated` con las etiquetas del Excel; no añade reglas.
- `qc_summary`, opcional, conserva los cinco campos manuales existentes del renglón de totales: `label_brand`, `packing_date`, `plu_coo`, `open_rating` y `color_rating`. Se escriben en A, D, H, J y K de esa fila; quedan vacíos si no se capturan. No se infieren desde las muestras. La fila mantiene la visibilidad definida en la plantilla base.
- `samples[].image_bindings`, opcional, registra la asociación externa de cada imagen única al contexto; ver [contrato Vision](vision.md). No introduce campos en los outputs de modelos.
- El estado de cierre usa `inspector_name`, `inspector_confirmed`, `confirmed_at` y `observations`. Cada muestra conserva también `inspector_confirmed`, `inspector_final_decision` y `observations`. Son extensiones del flujo de confirmación solicitado, no outputs nuevos de modelos.
- `predictive` omite `predicted_loss_pct` con OFF. Con ON puede tener `status` y `reason` para explicar indisponibilidad sin bloquear las reglas.

No se crea `final_recommendation` de lote: cada muestra conserva su recomendación. Al confirmar, el servidor recalcula desde la captura actual y guarda la decisión humana sin sustituir la recomendación. La interfaz muestra los resultados y sugerencias de todas las paletas antes de los campos de decisión. Editar el Level Flag u otros campos finales conserva los cálculos y retira la confirmación previa; cambiar las mediciones QC o la evidencia exige evaluar de nuevo.

`reason_source`, opcional, identifica el origen del Reason. La captura nueva envía `"defect_summary"`: el servidor recalcula `generated_reason` desde las cantidades observadas y lo copia a `qc_header.reason`. Si el inspector ajusta la redacción, `"inspector"` conserva ese texto y mantiene el resumen calculado por separado. Remarks y Level Flag conservan su significado propio. Las capturas anteriores sin este campo mantienen su Reason registrado.

`confirmed_at` se guarda en UTC para trazabilidad; en el Excel se presenta en `America/Lima`.

Cuando una muestra se inicia desde el manifiesto, conserva `reception: {scan_input, records}` como procedencia opcional. Los nombres/celdas originales de esas filas se preservan y deben corresponder al lote/paleta de la muestra. El footer SmartFruit muestra la lectura, cantidades declaradas/recibidas y origen del registro; no sustituye las mediciones QC. El campo `reception` no cambia ningún output de Vision o Predictive ni crea reglas de recepción.

El flujo por lote añade opcionalmente `lot_reception` (padrón de recepción), `lot_summary` (cantidades y porcentajes de los dieciséis defectos) y `generated_reason` (descripción calculada, revisable). Mantiene una fila por paleta y exige Level Flag del inspector al confirmar un lote nuevo. No deduce ese Flag de la severidad por muestra. La vista imprimible conserva los campos del reporte y usa el diálogo del navegador para guardar PDF. Ver [flujo por lote](../lot_workflow.md).
