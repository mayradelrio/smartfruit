# Datos y distribución

## Git local

Se versionan documentación, configuración, código del MVP, scripts de referencia y ejemplos de demo. El inventario de originales `docs/source_inventory.json` se conserva únicamente en el entorno local y está excluido de Git.

Se excluyen `data/local/`, `notebooks/originals/`, reportes generados, secretos, entornos, cachés y artefactos de modelos. No añadir datos reales con `git add -f` ni convertir un reporte completado en plantilla pública. El manifiesto dummy autorizado sí se publica en `examples/reception/SmartFruit_reception_manifest_demo.csv` para pruebas y demostraciones; esta excepción no autoriza otros datos operativos ni Excel completados.

Los nombres, metadatos y hashes de originales privados permanecen en el inventario local. Los tres JSON de ejemplo son predicciones por crop de las fotos usadas en la demo, sin asociación comercial acreditada.

## Entrega descargable

Una entrega pública para Visual Studio Code incluye código, documentación, configuración compartida y ejemplos autorizados. Los adjuntos privados conservan sus rutas ignoradas y no se añaden a Git ni a esa entrega. Cualquier archivo de respaldo que incluya originales debe mantenerse privado.

`scripts/package_project.py` genera por defecto un ZIP de código, documentación y ejemplos. La opción `--include-originals` añade adjuntos del inventario local y se reserva para respaldos privados; no debe utilizarse para una entrega pública. El paquete predeterminado excluye historial `.git`, credenciales, entornos virtuales, `node_modules`, pesos y reportes generados.

Antes de publicar se debe revisar el contenido seleccionado para Git. Las licencias y los permisos de redistribución de código, datos y modelos deben quedar definidos por su propietario.

## Site privado

Un despliegue web puede prepararse desde un checkout separado. Su configuración, rutas y credenciales de acceso se mantienen fuera del repositorio público. El runtime incluye interfaz, adaptador, módulos por allowlist, plantilla saneada y tres JSON técnicos. No incluye los originales operativos excluidos del repo principal.

La opción `--project-archive` del constructor web permite ofrecer un ZIP descargable. Para una publicación pública debe recibir únicamente un paquete previamente revisado, sin originales privados ni reportes completados. Los respaldos privados no deben incluirse como assets de una entrega pública.

Los nuevos datos QC se calculan y guardan en el navegador; no se envían a Sites. El historial del navegador no equivale a una copia de seguridad ni a sincronización entre dispositivos.

## Captura, borradores y asociaciones

IndexedDB conserva por separado el manifiesto activo, el borrador QC y los reportes confirmados. El borrador puede contener datos incompletos, nombre del inspector, recepción seleccionada, JSON Vision originales y `image_bindings`. El guardado y la recuperación eliminan los estados de confirmación del envoltorio y de las muestras; no modifican campos internos del JSON Vision ni sus claves adicionales. Recuperar captura no recupera aprobación.

Las asociaciones externas contienen `image_id`, `sample_id`, `pallet_id` y `lot_id`; son contexto de integración y no una modificación del contrato Vision. Cada muestra conserva solo sus filas de recepción; el nuevo contenedor opcional `lot_reception` conserva el padrón completo del lote seleccionado para comprobar que no faltan ni se mezclan paletas. El resumen manual `qc_summary`, cuando se captura, se conserva como dato del inspector.

La indicación visible Recepción/Vision/Inspector se calcula desde la captura actual. No constituye una auditoría de todas las ediciones ni verifica identidad o autoría. Los pendientes permanecen distintos de cero.

La app informa fallos de guardado o recuperación; no promete persistencia si el navegador deniega almacenamiento, agota su cuota o se borran sus datos. La recuperación no cruza navegadores, dispositivos u orígenes web. Descargar Excel y JSON de los reportes conserva copias independientes; el guardado automático no es un respaldo externo.

En FastAPI, la evaluación y confirmación se envían al servidor configurado y los reportes se guardan en `reports/`; el borrador automático continúa en el navegador. En el Site, el adaptador ejecuta Python y persiste la captura en el navegador, sin enviar datos QC a Sites. Esta distinción evita confundir el almacenamiento del servidor local con IndexedDB.
