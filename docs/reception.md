# Recepción: criterios confirmados por el negocio

El checker y el sistema actual completan la recepción y colocan las etiquetas antes de la inspección. En la web **QUALITY INSPECTION**, SmartFruit comienza al cargar el manifiesto y seleccionar el lote recibido; consultar una etiqueta interna existente es una alternativa opcional. El MVP consulta el CSV cargado en el navegador; la conexión en vivo al sistema actual sigue pendiente. Esta documentación describe el contrato de recepción sin publicar datos de reportes QC completados.

## Dos entradas

| Compra | Documento | Paletas |
|---|---|---|
| Internacional | Packing list con detalle de paletas | El checker utiliza los números del proveedor y el sistema actual genera la etiqueta con el código propio de la empresa |
| Nacional | Orden de compra con producto, tamaño y cantidad de cajas | El checker registra la distribución real recibida por paleta, cajas y contenido; el sistema actual asigna nuevos números de paleta y genera las etiquetas internas |

La generación de números, el armado/distribución de paletas y la impresión de etiquetas pertenecen al proceso existente. SmartFruit conserva esos identificadores y consulta sus datos; no debe generar una segunda numeración ni etiquetas nuevas.

En ambos casos se reciben paletas asociadas a un lote. El lote existe también en compra nacional, aunque no haya contenedor. `Container` y `AgroPeru Lot Number` conservan campos separados, como en el QC Report.

Según la regla indicada por el negocio, la ausencia confirmada de contenedor en un reporte completado representa compra nacional. En una captura pendiente, un campo aún no completado no acredita por sí solo que esa ausencia haya sido confirmada.

La clasificación de compra no sustituye `Country Of Origin`: el tipo de compra y el origen del fruto se registran por separado.

## Consideraciones del formato

- La detección de tablas importadas debe usar las etiquetas de la hoja `Report`, porque la fila de encabezados puede variar.
- Los identificadores de lote y paleta pertenecen a entidades distintas; una coincidencia entre sus textos no permite unificarlos.
- La recepción debe admitir varios tamaños o líneas de contenido en una misma paleta, sin elegir una por inferencia.
- `Sample` describe la muestra inspeccionada. No permite deducir cajas recibidas, capacidad por paleta ni reglas de paletización.

## Recorrido previsto

1. Proceso existente: disponer del packing list o la OC y recibir el camión.
2. Checker: revisar lo recibido y registrar la distribución real en el sistema actual.
3. Sistema actual y checker: generar y colocar las etiquetas internas en las paletas, en ambos tipos de compra.
4. Inicio de SmartFruit: el inspector carga el manifiesto. Si contiene un único lote, queda seleccionado automáticamente; si contiene varios, elige cuál revisar. También puede consultar una paleta por su número o código de etiqueta.
5. SmartFruit muestra el lote y todas sus paletas, con los datos disponibles de recepción, conservando su procedencia y sin volver a introducirlos manualmente cuando ya existan.
6. El inspector crea la muestra QC y continúa con Vision para oleocelosis, otros defectos manuales, reglas, recomendación y confirmación final. El reporte hereda los datos de recepción confirmados.

El contenido recibido de la paleta y la muestra QC tienen denominadores distintos: las cajas/contenido provienen de recepción; `Sample` y los frutos evaluados por Vision corresponden a la muestra inspeccionada. No sustituir uno por el otro.

Los identificadores ya existentes en el proyecto son `shipment_id`, `scan_code`, `scan_level`, `lot_id`, `pallet_id`. La referencia actual del manifest contiene `scan_level=PALLET`, `size_declared`, `expected_count_per_box`, `boxes_received` y `qty_received_weight`. `expected_count_per_box` describe frutos por caja; no define cajas por paleta.

`scan_code` se resolverá contra el registro del sistema actual. El patrón de los códigos de la demo no demuestra el formato de una etiqueta real. No reconstruir el código a partir de lote/paleta ni asumir que el código de la empresa y el número del proveedor son el mismo dato.

## Consulta de lotes y paletas mediante CSV

Está confirmado que el sistema actual genera los identificadores y el checker realiza ese trabajo antes de QC. Ya no corresponde definir en SmartFruit una capacidad por paleta ni una regla de numeración nacional.

La consulta admite el número de paleta registrado en el manifiesto CSV; no se necesita una foto de etiqueta para esta modalidad.

El flujo principal permite abrir directamente un lote. Un archivo de un solo lote presenta sus paletas automáticamente; con varios lotes, se selecciona uno y se pulsa **Revisar lote**. **Continuar · cargar Vision** prepara la inspección completa. No hace falta buscar una paleta para iniciar este flujo.

`reception.py` valida y carga el CSV, acepta separador punto y coma o coma y BOM UTF-8, y busca coincidencia exacta contra `pallet_id` o `scan_code`. Conserva ceros iniciales y filas originales. Si un código identifica más de una recepción exige contexto de lote en lugar de elegir una fila silenciosamente.

El manifiesto dummy autorizado se distribuye en `examples/reception/SmartFruit_reception_manifest_demo.csv`. Contiene siete filas/paletas del lote 5815 y lo selecciona automáticamente al cargarlo. `5815` es el identificador de prueba del lote en ese CSV. La búsqueda opcional de paletas admite el identificador dummy `5645`; un identificador ausente del CSV devuelve **Paleta no encontrada**. Estos datos de demostración no acreditan una recepción comercial ni se obtienen de los Excel privados.

`POST /api/reception/lot` admite `{manifest_csv, lot_id}` sin `scan_input`: devuelve `selection_mode: "lot"` y `scanned_pallet_id: null`. Si se aporta `scan_input`, conserva la consulta exacta por paleta y devuelve `selection_mode: "scan"`. Ambas modalidades incluyen todas las filas y selecciones por paleta del lote. `/api/reception/resolve` sigue siendo una consulta de paleta individual.

Se precargan los datos explícitos disponibles por paleta, incluido **Label** desde `label_brand`, fecha de empaque, Size y los demás campos compatibles. En el resumen QC, Label, Packing date y PLU/Coo se precargan solo cuando son uniformes en el lote. `expected_count_per_box` no se convierte en medición de `Avg. Count per Box.` ni en cantidad de muestra. Si hay varios tamaños en una paleta se conservan todas sus filas y el campo QC Size queda para completar según la inspección.

Cada muestra conserva `reception: {scan_input, records}` con una copia de las filas de esa paleta. El flujo valida que coincidan con su lote/paleta y el reporte digital conserva esta procedencia. Reemplazar el CSV activo no cambia inspecciones ya iniciadas.

El padrón del lote conserva `lot_reception: {lot_id, records}` cuando se abre directamente, o `{scan_input, records}` con la consulta por paleta. La apertura directa no afirma que se haya realizado un escaneo. Los JSON se asignan por paleta y la captura manual continúa en formularios agrupados en General Information, Condition y Quality; el resumen compacto del lote es de solo lectura. Ver [flujo por lote](lot_workflow.md).

En el Site, el CSV importado queda en IndexedDB del navegador, separado del historial de reportes. Se puede retirar o reemplazar; no se envía ni se incorpora automáticamente a los assets publicados. El repositorio sí incluye el manifiesto dummy autorizado en `examples/reception/SmartFruit_reception_manifest_demo.csv` para importarlo manualmente. Los manifiestos operativos reales y los Excel completados permanecen excluidos. La búsqueda usa el archivo importado, sin afirmar una conexión en tiempo real al sistema de la empresa.

El packing list y la OC son fuentes del proceso de recepción existente. Para iniciar SmartFruit después del checker, la integración prioritaria es con sus registros confirmados. Un reporte QC completado documenta la inspección; no define el formato de las etiquetas ni la consulta del sistema actual.
