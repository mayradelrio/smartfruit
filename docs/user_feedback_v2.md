# Segunda prueba de usuario · 18/11/2026

El MVP anterior está preservado por el tag `pre-user-feedback-2026-11-18` (commit `d847c4f`). La implementación se desarrolla en `feat/user-feedback-v2`.

Commit de implementación: `048491247a890ad1f2a237fd1ca5bfc20c0cb13d`.

## Flujo

```text
Manifiesto → lote → seleccionar paleta / omitir con motivo opcional
  → primera caja → fotos grupales / JSON → revisar sospechas Vision
  → completar defectos QC → evaluar → STANDARD: cerrar
                                     EXTEND: segunda caja
  → segunda caja → fotos + revisión QC + defectos → COMPLETE
  → Level Flag humano → confirmar → report.xlsx + report.json + source.json
```

La severidad 1 sugiere STANDARD; las severidades 2 y 3 sugieren EXTEND. La segunda caja cierra la ampliación y el servidor rechaza una tercera, incluso si se envía un historial manipulado. No existe una acción comercial ESCALATE para el inspector. Una ampliación pendiente no permite confirmar el reporte.

## Cambios

- **Decisión y paletas:** `business_rules.py`, `decision.py`, `additional_review.py`, `lot_inspection.py`, `inspection.py` y `workflow.py`. Estados PENDING, SELECTED, IN_PROGRESS, COMPLETED y SKIPPED; las omitidas no generan mediciones y se conservan en el padrón del lote.
- **Revisión de Vision:** `vision.py`, `vision_review.py`, `vision_validation.py` y `web/vision_review.js`. Cada positivo conserva clase, probabilidad y confianza originales, además de estado, revisor, fecha y corrección. Un check por foto/detección permite incluir o excluir oleocelosis; todos comienzan marcados, salvo rechazos ya guardados. Una sola confirmación del conjunto sustituye los botones por positivo. Las exclusiones no incrementan otros defectos manuales.
- **Procesamiento:** `vision_capture.py` y `vision_inference.py`. Fases observables, avance por fotografías/frutos, prevención del doble envío, error/timeout diferenciados y reintento explícito. Las fotos de entrada se conservan en el trabajo local.
- **Interfaz:** `web/index.html`, `web/vision_capture.js` y utilidades de captura. Selección de paletas, revisión por detección, fotos grupales prioritarias y acciones según la etapa. Se reducen textos técnicos y explicaciones repetidas.
- **Reportes:** `qc_report.py`, `print_report.py`, `report_evidence.py` y `evidence_display.py`. Conteo confirmado, padrón con omisiones, auditoría de Vision, versiones y procedencia; se conservan las fotografías también al rechazar una predicción. Excel incorpora hojas Vision QC, Vision validation y Vision metrics.
- **Dominancia:** `defect_dominance.py`, versión 1.0.0, fuente `QC user validation 2026-11-18`, estado `stakeholder-validated`. Decay > Styler > Yellow Color > defectos superficiales. Solo resuelve etiquetas del mismo fruto identificado. Empates superficiales y etiquetas fuera del alcance quedan sin resolver.

## Compatibilidad

Los campos y clases del JSON binario original de Vision se conservan. Un positivo histórico sin revisión se considera pendiente; debe revisarse antes de evaluar. Las importaciones previas y los recortes individuales siguen disponibles. El adaptador del navegador incluye los módulos y assets nuevos.

Los checks son una selección de trabajo, almacenada opcionalmente en `qc_included`. Marcado incluye la detección y desmarcado la excluye; puede corregirse de nuevo antes de cerrar la caja. QC registra su nombre una vez y confirma el conjunto con **Aplicar selección** para JSON importados o **Incorporar fotos** para resultados procesados. Hasta ese paso los positivos nuevos siguen pendientes para el servidor. Una exclusión sin clasificación específica conserva `override_label: "other"` y el motivo `Excluido por QC mediante el check de oleocelosis.`, sin exigir otro formulario. La predicción original y su evidencia permanecen intactas.

Los thresholds y sus fronteras existentes se conservan. Los reportes históricos pueden mostrar EXPAND/ESCALATE; las capturas nuevas usan STANDARD/EXTEND/COMPLETE. EXPAND se admite como alias de entrada de EXTEND, sujeto al límite de dos cajas. No se migran ni sobrescriben archivos de reportes históricos.

El Level Flag sigue siendo humano, Level 3 permanece representable y Predictive conserva su configuración inicial OFF. No se incorporan pérdidas predictivas, decisiones comerciales, pesos ni thresholds nuevos. La dominancia procede de la validación QC y no de la matriz histórica; no modifica conteos agregados sin identidad por fruto.

## Métricas operativas

El reporte JSON conserva `vision_validation.dataset` y sus métricas. Cada fila contiene image_id, crop_id, model_prediction, model_probability, qc_final_label, error_type, notes y auditoría. Los negativos no adjudicados quedan pendientes y no se suponen sanos. Precision, recall, F1, matriz de confusión, FP y FN describen únicamente el subconjunto adjudicado; la cobertura y el alcance se informan junto a los valores.

`POST /api/vision/validation` acepta:

```json
{
  "vision_records": ["objetos JSON de Vision, no rutas"],
  "adjudications": [
    {
      "image_id": "PHOTO_...",
      "crop_id": "..._L01.jpg",
      "qc_final_label": "oleocellosis",
      "notes": "Negativo del modelo revisado por QC"
    }
  ]
}
```

El ejemplo ilustra la forma del cuerpo: reemplazar el primer elemento por un objeto Vision válido. La respuesta devuelve dataset y metrics sin alterar la inspección. Las adjudicaciones de negativos permiten registrar falsos negativos. Labels finales: oleocellosis, styler, scar, inking, clean, other y not_oleocellosis.

No hay una muestra operativa completa adjudicada por QC en el repositorio. Su captura y medición requieren la siguiente sesión con el inspector; los tests sintéticos no acreditan exactitud del modelo. Tampoco se implementa un clasificador multiclase ni identificación completa de todos los defectos por fruto.

## Demo

1. Ejecutar `python -m smartfruit.app` y abrir `http://127.0.0.1:3000`.
2. Usar **Cargar demo técnica**. Las tres sospechas aparecen marcadas; desmarcar una, registrar el revisor una vez y pulsar **Aplicar selección**. Verificar que el conteo operativo queda en dos y que las predicciones originales se conservan.
3. Completar los defectos manuales y cerrar la captura de la primera caja. Evaluar y elegir STANDARD o EXTEND.
4. Para EXTEND importar `examples/vision/DEMO_ADDITIONAL_BOX_001.json`, ajustar los checks de sus dos sospechas, aplicar la selección y completar sus defectos. Verificar COMPLETE y ausencia de una tercera caja.
5. Para probar paletas, cargar `examples/reception/SmartFruit_reception_manifest_demo.csv`, abrir el lote 5815, seleccionar una paleta y omitir otra con motivo. Completar u omitir todas las pendientes antes de confirmar el lote.
6. Registrar el inspector y el Level Flag humano. Confirmar y descargar Excel/JSON; abrir la vista imprimible. Verificar las omisiones, auditoría y ambas cajas.
7. Con pesos locales disponibles, seleccionar varias fotos grupales de una caja. Observar progreso automático; un segundo clic no debe iniciar otro trabajo. Un fallo permite reintentar.

## Verificación

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
npm.cmd test
```

Las nuevas pruebas cubren decisiones L1/L2/L3, cierre de segunda caja y rechazo de tercera, selección/omisión y persistencia, confirmación/rechazo y auditoría, dominancia por fruto, avance/doble envío/errores/reintentos, métricas parciales y reportes con evidencia tras una corrección. Los datos operativos, pesos, fotografías y reportes locales siguen excluidos de Git.

Resultado de esta iteración: **736 tests Python aprobados, 2 omitidos; 154 tests JavaScript aprobados; Ruff sin errores**. FastAPI/Starlette emite un aviso de deprecación del transporte httpx del entorno, sin fallos de prueba. `npm.cmd` evita depender de la política de ejecución de scripts PowerShell.

Actualización de checks: **168 tests JavaScript aprobados; 152 tests Python de los módulos afectados aprobados, 1 omitido; Ruff sin errores**. Incluyen selección inicial activa, desmarcar/volver a marcar, exclusiones guardadas, auditoría del conjunto y conservación de evidencia.

La prueba gráfica quedó pendiente: Chrome local no habilitó la conexión de automatización en el entorno de ejecución. Los tests JavaScript ejecutan las funciones reales con un DOM de prueba; no acreditan paginación ni gestos en un navegador. La inferencia se verifica con stubs controlados; falta adjudicar fotografías operativas con QC y medir el modelo real.
