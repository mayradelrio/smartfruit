# Validación del formato QC en Excel

La exportación usa una plantilla QC vacía validada contra la referencia pública de layout. Las comparaciones adicionales con originales privados comprueban los campos comunes sin distribuir sus datos. La personalización autorizada incorpora la identidad **AgroPeru** y la etiqueta `AgroPeru Lot Number` en las dos plantillas limpias. La fidelidad se refiere al formato y al tratamiento de los campos; la marca y la etiqueta de lote son adaptaciones deliberadas. Los originales privados conservan su contenido.

## Método y alcance

`tests/test_qc_reference.py` reconstruye una entrada del renderer directamente desde las celdas de los Excel privados: cabecera, detalle y resumen manual. No ejecuta Vision, Predictive ni Business Severity, no fabrica predicciones y no asocia fotografías a datos históricos. Las señales de modelos se dejan sin evaluar; los reportes de prueba son borradores.

La comparación de estilos usa propiedades semánticas —fuente, relleno, borde, alineación, protección, formato numérico y prefijo de texto—, no los IDs de estilo, que son internos de cada workbook.

Los archivos operativos permanecen en `data/local/originals/qc/`, fuera de Git. La fixture versionada `tests/fixtures/qc_layout_reference.json` contiene únicamente etiquetas, huellas de estilos y geometría del layout, sin valores de inspección, identificadores de lotes/paletas ni nombres de personas. Permite comprobar el formato aun cuando los originales privados no estén disponibles.

## Evidencia comprobada

| Elemento | Resultado |
|---|---|
| Hoja y 29 encabezados de columnas | Se comprueban nombres y orden; salida en la hoja `Report`. |
| Cabecera de la plantilla base | Se conservan los campos capturados; no se infieren las decisiones del inspector. |
| Detalle A–AB | Se conservan las cantidades y valores capturados en las columnas correspondientes, con filas dinámicas por muestra. |
| Resumen manual del renglón de totales | Se conservan los valores explícitamente capturados de Label, Packing date, PLU/Coo, Open Rating y Color Rating. No se deducen desde el detalle. |
| Fórmulas y resultados | Porcentajes por muestra, sumas de cantidades, porcentajes por defecto y total combinado coinciden con el cálculo de las fuentes; se comparan también sus cachés guardadas cuando existen. Pulp conserva el SUM original, que ignora texto. |
| Estilos del master | Coinciden las propiedades de las 754 posiciones A1:AC26, incluyendo bordes, fuentes, alineaciones y formatos. |
| Geometría del master | Se conservan anchos de columnas, alturas, visibilidad y agrupación de las filas originales y combinaciones de celdas del núcleo. La fila de totales permanece oculta como en el master. |
| Logo | AgroPeru sustituye la imagen de las plantillas limpias. Mantiene la posición inicial y la altura, con el ancho ajustado para conservar su proporción dentro del área histórica. La referencia de píxeles y el extremo derecho del anclaje reflejan la marca autorizada. El texto alternativo identifica AgroPeru. |
| Sección SmartFruit | Empieza después del núcleo QC y no sustituye campos ni celdas del reporte original. |
| Originales | Las pruebas verifican que sus hashes no cambian durante la exportación. |

Los formatos de entrada pueden situar los encabezados en filas diferentes. La prueba localiza la fila por sus etiquetas y compara las columnas correspondientes; la exportación usa el layout de la plantilla vacía. Esto no equivale a reproducir todas las variantes de presentación de los archivos de entrada.

## Correcciones efectuadas durante esta validación

- Conservar el formato de fecha de la plantilla, en lugar de forzar otro formato de presentación.
- Conservar las alturas particulares, visibilidad y atributos de agrupación de las filas del master; las filas adicionales reutilizan los estilos del cuerpo y del cierre de la tabla. La fila dinámica de totales mantiene la condición oculta de la fila 24 del master, aunque la copia limpia se haya dejado visible para inspección.
- Evitar que un PLU/Coo numérico de otro reporte se reinterprete como fecha por un formato heredado de la plantilla.
- Recuperar la semántica del SUM de Pulp: no convertir silenciosamente los textos numéricos en mediciones ni ocultar el total por exigir cantidades numéricas en todas las filas.
- Admitir `qc_summary` opcional con las cinco claves existentes `label_brand`, `packing_date`, `plu_coo`, `open_rating`, `color_rating`. Se escriben, respectivamente, en A, D, H, J y K de la fila dinámica de totales. Si no se capturan, quedan en blanco. Se conservan como texto literal cuando corresponde.

## Diferencias deliberadas y límites

- La identidad AgroPeru y la etiqueta `AgroPeru Lot Number` son personalizaciones autorizadas respecto de los reportes históricos; no se exige fidelidad literal a su marca original. La sustitución se realiza dentro del ZIP del Excel, conservando las partes de celdas, estilos y relaciones. El PNG de 2137 × 736 se presenta sin estirarlo: conserva el origen y la altura de 1314426 EMU, reduce el ancho a 3816479 EMU y ajusta solo el extremo derecho del dibujo dentro del espacio anterior. Se actualiza también su atributo descriptivo. La etiqueta visible del lote se adapta a AgroPeru y conserva la clave interna `lot_id`; las restantes etiquetas de negocio mantienen su contrato. La vista imprimible lee el mismo PNG de la plantilla y hereda esta marca, conservando su proporción.
- Las fórmulas de cantidades y porcentajes llevan controles de datos pendientes y denominador. Su texto no es idéntico al original: con datos completos mantienen los mismos resultados; con datos incompletos quedan en blanco en lugar de aparentar cero o dividir por cero. Pulp conserva su SUM original.
- La cantidad de filas se ajusta al número de muestras. Las celdas de totales se desplazan y sus referencias se actualizan; no se truncan muestras.
- Las combinaciones decorativas vacías posteriores al núcleo se sustituyen por la sección SmartFruit. La fila de sumas y sus cinco campos manuales siguen presentes y ocultos como en el master; no se trasladan ni se infieren sus valores.
- Se añaden marca de borrador/confirmado, trazabilidad y sección SmartFruit, área de impresión, repetición de encabezados, orientación horizontal y ajuste al ancho de página.
- Se eliminan los metadatos personales del archivo fuente. No se copian sus datos operativos a la plantilla limpia.
- Se validó la estructura del workbook y sus datos con openpyxl. **No se verificó igualdad visual píxel a píxel ni la paginación en Excel/impresora.** Fuentes instaladas, escalado y aplicación lectora pueden afectar la presentación. No se debe afirmar identidad visual exacta con los archivos de referencia.

## Verificación reproducible

```bash
python -m pytest tests/test_qc_reference.py tests/test_qc_report.py tests/test_report_photo_evidence.py tests/test_lot_flow.py -q
```

Las pruebas cubren fidelidad QC, persistencia del logo AgroPeru en Excel/impresión y evidencia fotográfica. Las comparaciones privadas se omiten explícitamente cuando no están los originales; las comprobaciones del layout de referencia, resumen manual, identificadores numéricos y semántica de Pulp siguen ejecutándose con datos sintéticos. Las comparaciones locales comprueban también la integridad de los originales. Este procedimiento no prueba modelos ni cambia reglas o thresholds.
