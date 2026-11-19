# Acceso desde ChatGPT en un navegador

La app FastAPI sigue disponible para ejecución local. El adaptador de esta carpeta permite servir la misma interfaz como Site privado y ejecutar los módulos Python existentes en el navegador mediante Pyodide. No reimplementa reglas ni modelos.

`build_site.py` copia la interfaz e inserta `bridge.js`, empaqueta los módulos Python mediante una lista explícita y añade la plantilla saneada y tres JSON técnicos. Incluye `box_inspection`, `additional_review`, `lot_inspection`, `lot_summary` y `print_report`, además de los módulos de captura, reglas y reporte. Los módulos conservan sus bytes y se registran en `source_provenance.json`. También se copian los assets JavaScript de la interfaz. `browser_api.py` adapta las peticiones de la interfaz a esas funciones; no crea otros defectos ni thresholds.

Pyodide 0.27.7, Python 3.12.7 y Pillow 10.2 se sirven desde el mismo Site. `runtime_assets.json` fija sus SHA-256. Los assets oficiales proceden de `https://cdn.jsdelivr.net/pyodide/v0.27.7/full/`. No hay peticiones a CDN ni envíos de datos QC durante el uso de la app.

Ejemplo de empaquetado desde el checkout principal, con los assets oficiales previamente descargados y verificados:

```bash
python hosting/browser/build_site.py \
  --runtime-assets /ruta/assets/pyodide \
  --licenses /ruta/assets/licenses \
  --output /ruta/site/dist
```

La publicación puede prepararse desde un checkout de entrega separado, manteniendo su configuración privada fuera del repositorio. SmartFruit continúa siendo la fuente de los módulos y de este adaptador. No se incluyen Excel completados, notebooks originales, manifiestos operativos reales ni ZIP operativo de Vision en la publicación. El CSV dummy autorizado se distribuye en `examples/reception/SmartFruit_reception_manifest_demo.csv` del repositorio para importarlo manualmente; este constructor no lo precarga en el runtime.

## Persistencia

`drafts.js` guarda una captura incompleta en IndexedDB sin exigir un QC evaluable. Al recuperar conserva campos, recepción, JSON originales y `image_bindings`, y retira estados de aprobación. La interfaz debe reevaluar y requerir nuevamente las decisiones y la confirmación del inspector. Las operaciones se serializan y el resultado de guardado se informa solo después de completarse la transacción. Un borrador incompatible no se sustituye automáticamente.

Cada confirmación guarda reporte, captura y Excel juntos en IndexedDB antes de mostrar éxito. Los reportes permanecen en ese navegador y se pueden recuperar mediante el historial de la interfaz. No se sincronizan entre dispositivos. Descargar Excel y JSON conserva una copia independiente; borrar datos del navegador elimina el almacenamiento local.

La interfaz usa una base IndexedDB separada para conservar el CSV de recepción importado. Solo las filas seleccionadas se incluyen en cada muestra/reporte; cambiar el manifiesto activo no cambia esas copias. Un CSV operativo real no se empaqueta ni publica como asset. Esta restricción no afecta a la copia dummy autorizada disponible en `examples/reception/SmartFruit_reception_manifest_demo.csv`.

La identidad de acceso del Site es la cuenta ChatGPT autorizada. El nombre del inspector y su decisión siguen siendo los campos de confirmación del MVP, sin firma criptográfica nueva. Predictive permanece OFF en esta entrega web.

## Trazabilidad y transporte

`POST /api/vision/import` permite validar importaciones atómicas antes de completar QC. Devuelve los JSON originales, el agregado y asociaciones externas por imagen, lote, paleta y muestra. Un duplicado idéntico deja trazabilidad sin inflar cantidades; otro contenido o una muestra diferente se rechazan. La evaluación vuelve a comprobar las asociaciones enviadas.

`field_sources.js` presenta procedencia contextual y pendientes; no persiste un historial autenticado de ediciones. El `qc_summary` opcional conserva los cinco campos manuales del renglón de totales del QC real. La exportación mantiene el contrato de reporte del paquete principal.

## Verificación

Las pruebas Python comparan backend, módulos centrales y adaptador. Las pruebas Node usan `fake-indexeddb` para comprobar persistencia y recuperación de borrador y verifican la presentación de procedencia. El runtime Pyodide se comprueba con Node como evidencia técnica separada de una sesión gráfica. Ver [validación](../../docs/validation.md) para los resultados de la entrega.

No se certificó una sesión de navegador del despliegue ni igualdad visual o paginación idéntica del Excel. Las pruebas de IndexedDB simulado y del transporte no sustituyen esa validación del flujo en un navegador real.

El bundle incluye `lot_inspection`, `lot_summary` y `print_report`. Soporta el padrón completo del lote, resumen aritmético de sus dieciséis defectos y vista HTML imprimible. La salida PDF utiliza el diálogo nativo del navegador. Ver [flujo por lote](../../docs/lot_workflow.md).

## Descarga del proyecto desde un navegador

La opción explícita `--project-archive /ruta/SmartFruit_VSCode.zip` comprueba el ZIP, lo copia a `downloads/` junto con su SHA-256 y añade un botón de descarga al inicio de la página, disponible antes de preparar Python. Para un despliegue público debe usarse un paquete revisado sin originales privados ni reportes completados. La comprobación de integridad ZIP no verifica por sí sola la privacidad del contenido. Construir sin esa opción retira esos dos assets y el botón de descarga.
