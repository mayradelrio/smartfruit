# Pruebas del MVP

Ejecutar `python -m pytest -q` con las dependencias de desarrollo instaladas. Las pruebas cubren contratos y resultados, no entrenamiento de modelos.

Para la persistencia y presentación del cliente: `npm ci` y `npm test`. Estas pruebas ejecutan Node con `fake-indexeddb`; no abren un navegador ni inician un servidor de vista previa.

Las comprobaciones de captura que no requieren dependencias también se pueden ejecutar con `node --test tests/js/test_field_sources.cjs tests/js/test_qc_ui.cjs tests/js/test_draft_lot_provenance.cjs`. El DOM de estas pruebas es simulado; no acredita la apariencia visual ni la persistencia de IndexedDB en un navegador real.

- `test_vision.py`: contrato, coherencia, agregación ponderada y duplicados.
- `test_business_rules.py`: fronteras, dominios y equivalencia con las reglas originales.
- `test_qc_report.py`: estructura Excel, saneamiento, fórmulas, trazabilidad y decisión humana.
- `test_workflow.py`: integración de captura, reglas, Predictive opcional y confirmación.
- `test_app.py`: API, exportación y persistencia.
- `test_browser_adapter.py`: el transporte para Sites conserva el flujo Python, el Excel, los datos de captura y la confirmación humana.
- `test_reception.py`: CSV, identificadores, ambigüedades y paletas con varios tamaños.
- `test_reception_flow.py`: escaneo → precarga → QC → reporte, con las filas originales de recepción preservadas.
- `test_lot_selection.py`: apertura directa por lote sin escaneo, precarga de Label, integridad del padrón y confirmación/exportación con su procedencia original.
- `test_reason_workflow.py`: Reason desde el resumen actualizado, redacción del inspector, compatibilidad histórica y conservación de sugerencia y decisión distintas en ambos transportes.
- `test_additional_review.py`: cajas adicionales por paleta, sumas ponderadas, integridad del historial y rechazo atómico de JSON repetidos o cantidades incompletas.
- `test_additional_review_flow.py`: preview, ampliaciones repetidas, compatibilidad de transportes y confirmación/exportación del acumulado.
- `test_additional_review_exports.py`: revisión inicial, adicionales y acumulado en Excel/impresión, conservando una fila principal por paleta.
- `test_lot_flow.py`: compatibilidad de API y funciones de la interfaz para abrir todas las paletas, tanto por lote como por escaneo; incluye una copia local opcional del manifiesto dummy autorizado; su versión distribuible está en `examples/reception/SmartFruit_reception_manifest_demo.csv`.
- `test_image_binding.py`: importación atómica, contexto lote/paleta/muestra, asociaciones externas y conflictos.
- `test_traceability_flow.py`: paridad backend/browser de importación, conservación de asociaciones, resumen QC y assets JavaScript.
- `test_qc_reference.py`: comparación de datos y formato del master QC, con referencia de layout sin datos operativos y casos privados opcionales. Ver [fidelidad QC](../docs/qc_fidelity.md).
- `js/test_drafts.cjs`: guardado/recuperación de captura incompleta, preservación de originales, retirada de aprobación, cuotas/errores y versiones incompatibles.
- `js/test_field_sources.cjs`: procedencia contextual, pendientes, ceros observados y tamaños mixtos sin completar mediciones.
- `js/test_qc_ui.cjs`: captura agrupada por paleta, precarga del manifiesto, navegación sin perder cantidades, resumen sin controles duplicados y registro explícito de ceros.
- `js/test_review_ui.cjs`: resultados y sugerencias antes de decidir, Reason precargado y edición final sin perder la evaluación; cambios QC exigen reevaluación.
- `js/test_additional_review_ui.cjs`: estado del inspector junto a la sugerencia, acción EXTEND y actualización aislada del acumulado con historial.
- `js/test_draft_lot_provenance.cjs`: validación de procedencia por lote o escaneo sin dependencias de IndexedDB.
- `js/test_reload_ui.cjs`: recarga sin lote activo, recuperación explícita y protección del borrador pendiente.
- `js/test_reception_storage.cjs`: límites de espera y cierre/aborto de almacenamiento del manifiesto.

## Agregación

- Una imagen y varias imágenes: sumar cantidades y calcular porcentaje sobre el total, no promediar porcentajes de fotos.
- Repetir un `image_id` no debe aumentar frutos, afectados ni confianza; debe dejar trazabilidad.
- Resolver explícitamente registros distintos con el mismo `image_id`.
- Validar tipos, campos obligatorios, cantidades, predicciones, porcentajes y confianza.
- Manejar entradas vacías y muestras sin frutos sin división por cero ni decisión de aceptación implícita.
- Separar las muestras; no mezclar todos los JSON de un ZIP como una muestra comercial.
- Validar el lote de archivos antes de incorporarlo: si alguno falla, conservar las fotografías ya cargadas y el resto de la captura.
- Asociar `image_id` a lote, paleta y muestra fuera del JSON Vision; rechazar reutilización entre muestras y cambios de contexto incompatibles.

## Reglas

- Las cuatro familias existentes y ambas políticas de frontera, incluidos valores por debajo, en y por encima de 1, 5, 10 y 20 según corresponda.
- Mapeo existente 1 → STANDARD, 2 → EXPAND, 3 → ESCALATE y motivos de severidad máxima.
- Entrada manual ausente distinta de cero; rechazar porcentajes fuera de dominio y valores no finitos.
- Ninguna regla inventada para columnas sin mapeo explícito.

## Flujo y reporte

- Recorrido completo con Predictive OFF, sin cargar modelos ni sus dependencias.
- Mantener cantidades, denominadores, campos QC y sección SmartFruit.
- Requerir y guardar confirmación/decisión del inspector; preservar su `Level Flag`.
- Con Predictive ON, un fallo no bloquea el flujo ni sustituye la recomendación de reglas.
- Mostrar `predicted_loss_pct` solo con Predictive activado.
- Conservar los cinco campos manuales opcionales del renglón de totales mediante `qc_summary`, sin inferirlos de las filas de muestras.
- Recuperar un borrador conserva datos incompletos, recepción y asociaciones; exige evaluar otra vez y confirmar nuevamente. IndexedDB simulado no acredita una sesión gráfica ni una persistencia entre dispositivos.
