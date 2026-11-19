# Arquitectura del MVP OFF

Estado: módulos implementados para el MVP OFF. Sus nombres son decisiones de organización, no campos nuevos en el JSON de Vision.

| Módulo en `src/smartfruit/` | Responsabilidad | Base existente |
|---|---|---|
| `vision.py` | Leer y validar JSON; agregar por muestra; deduplicar por `image_id`; trazabilidad de confianza | `load_vision_json`, `validate_vision_record`, `aggregate_vision_sample` |
| `vision_capture.py` | Catálogo de fotos locales, trabajos asíncronos, copias de entrada y contexto de lote/paleta/muestra | Selección del manifiesto e importación Vision existente |
| `vision_inference.py` | Clasificar recortes con los pesos ResNet18; recorrido opcional YOLO y ResNet para fotos completas | Arquitectura, clases y preprocesamiento del notebook; sin entrenamiento |
| `image_binding.py` | Validar importaciones atómicas y asociar cada imagen a lote, paleta y muestra fuera del JSON Vision | Contrato Vision sin cambios; contexto explícito de la inspección |
| `reception.py` | Cargar el manifiesto CSV y resolver el número/código de paleta con sus registros originales | Contrato existente del reception manifest |
| `inspection.py` | Captura QC, cantidades y denominadores; distinguir pendiente de cero; validar asociaciones y resumen QC opcional | Excel y `add_qc_defects` |
| `business_rules.py` | Reglas y mapa de defectos existentes; política de frontera explícita | `business_level`, `BUSINESS_DEFECT_MAP` |
| `predictive.py` | Flag `USE_PREDICTIVE`; OFF sin modelos; ON indisponible si no hay proveedor | `attach_predictive` y notebook, sin artefacto adjunto |
| `decision.py` | Recomendación y motivos basados en reglas; confirmación y decisión final humana | `evaluate_business_severity`, `build_final_report` |
| `qc_report.py` | Reporte digital basado en el Excel real; sección SmartFruit al final | Hoja `Report` de los dos ejemplos |
| `workflow.py` | Coordinar captura, reglas y recomendación por muestra | Flujo solicitado |
| `app.py` y `web/index.html` | API FastAPI, importación Vision y captura/revisión con contexto visible; persistir confirmaciones | Campos de los Excel reales |
| `web/drafts.js` | Guardar y recuperar la captura incompleta en IndexedDB, sin conservar aprobación | Datos de captura, JSON originales y asociaciones externas |
| `web/field_sources.js` | Mostrar procedencia contextual y campos pendientes | Recepción seleccionada, datos Vision y captura del inspector |
| `web/vision_capture.js` | Elegir fotos, mostrar progreso y confirmar resultados para la paleta o su revisión adicional | Catálogo y trabajos del servidor local; importación JSON como alternativa |
| `hosting/browser/` | Adaptador de transporte para Site privado; ejecutar los mismos módulos Python con Pyodide y persistir en IndexedDB | Misma interfaz, reglas y exportación, sin cambiar modelos |

## Límites

- Vision automatiza únicamente oleocelosis. Su contrato no cambia.
- Los otros defectos y campos QC se completan manualmente mientras no estén automatizados.
- Los datos originales del inspector se conservan; los porcentajes y recomendaciones son derivados trazables.
- El conjunto de fotografías de una muestra debe ser explícito. `POST /api/vision/import` valida la importación antes de incorporarla y devuelve `image_bindings` con `image_id`, `sample_id`, `pallet_id` y `lot_id`. Esas asociaciones pertenecen a la integración; no se agregan al output de Vision ni se infieren desde `partition` o el nombre de archivo.
- Se permite importar antes de completar la fecha y los defectos QC, pero lote, paleta y muestra deben estar definidos. Los duplicados idénticos se conservan como fuente y se ignoran en el agregado; un conflicto de contenido o de muestra se rechaza. La unicidad se controla dentro de la inspección, no mediante un registro global de fotografías.
- Las asociaciones proporcionadas se vuelven a validar al evaluar y confirmar. Cambiar un identificador sin actualizar correctamente el contexto impide usar asociaciones de otro lote, paleta o muestra.
- Deduplicar `image_id` no identifica un fruto repetido en fotos distintas.
- Predictive OFF no importa modelos ni requiere pesos o servicios predictivos. La inferencia Vision local es independiente y opcional: ejecuta sus pesos existentes en un proceso separado. Importar JSON no requiere ese entorno. Ver [Vision desde fotografías](vision_capture.md).
- Predictive no asigna ni reemplaza la recomendación de negocio. ON incorpora una señal si está disponible.
- La aplicación debe requerir y guardar confirmación/decisión del inspector. El JSON original solo declara `human_confirmation_required`; eso no implementa la confirmación.
- Se preserva el `Level Flag` del QC; no se identifica automáticamente con `business_max_level`.
- `qc_summary` es opcional y contiene las cinco claves existentes `label_brand`, `packing_date`, `plu_coo`, `open_rating` y `color_rating`. Sus valores manuales aparecen en el JSON y en la fila dinámica de totales del Excel, que conserva la visibilidad del master. No se infieren desde el detalle. Ver [fidelidad QC](qc_fidelity.md).
- El checker y el sistema actual identifican y etiquetan las paletas antes de QC. SmartFruit debe consultar esos registros al escanear la etiqueta interna y conservar sus números; no generar paletas ni etiquetas propias. Ver `reception.md`.

## Persistencia y transporte

El borrador activo se guarda en IndexedDB incluso con datos incompletos. La recuperación conserva captura, recepción, JSON Vision y asociaciones externas; descarta los estados de aprobación y obliga a reevaluar. Un error de cuota, formato o versión se informa y no autoriza a sobrescribir silenciosamente el borrador anterior.

Los reportes confirmados se guardan en `reports/<id>/` en FastAPI o en IndexedDB en el Site. El manifiesto y el borrador activo tienen almacenes separados. No existe sincronización entre dispositivos. Las descargas Excel/JSON sirven como respaldo independiente de los reportes.

El bundle web incluye diez archivos Python por allowlist, incluido `__init__.py`, y ejecuta la misma lógica con Pyodide. `browser_api.py` adapta el transporte; los assets `drafts.js` y `field_sources.js` se sirven tanto en FastAPI como en el Site. La vista de procedencia es contextual y no constituye un historial autenticado de ediciones.

## Pendiente

Consulta en vivo del sistema del checker (la importación CSV ya está implementada); artefacto Predictive real y adaptación de sus features por lote; equivalencias para defectos sin regla, aprobación operativa de fronteras y cualquier política de recomendación de lote. El Site privado ofrece acceso web con almacenamiento en el navegador; no sincroniza registros entre equipos ni sustituye la identidad operativa del inspector por una firma autenticada.

## Flujo por lote y entrega VS Code

`lot_inspection` valida el padrón recibido y exige una fila por paleta en capturas nuevas; `lot_summary` calcula totales y texto descriptivo sin inferir Level Flag; `print_report` ofrece una vista HTML autónoma imprimible. No cambian outputs de modelos ni reglas. El paso actual y el padrón se recuperan en el borrador. Ver [flujo por lote](lot_workflow.md) y [guía de instalación](../README.md).
