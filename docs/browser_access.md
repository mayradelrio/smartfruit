# SmartFruit en el navegador

El adaptador `hosting/browser/` permite ejecutar el MVP en un despliegue web con acceso configurado por su responsable. La dirección y los identificadores de un despliegue privado se mantienen fuera de esta documentación pública.

Para ejecutar la aplicación localmente, sigue la [instalación del README](../README.md). Las comprobaciones técnicas del código y del bundle no equivalen a una sesión de pruebas del navegador.

1. Abrir la dirección del despliegue configurado e iniciar sesión si su control de acceso lo solicita.
2. Esperar la primera carga y pulsar **Cargar manifiesto CSV**. Para la demo, seleccionar `examples/reception/SmartFruit_reception_manifest_demo.csv`, el manifiesto dummy autorizado para distribución pública.
3. Escanear o escribir el número de paleta y pulsar **Buscar paleta**. En el manifiesto dummy de demostración se puede probar 5645; 5824 no está registrado en ese archivo.
4. Revisar el lote y pulsar **Siguiente · cargar Vision**. Se prepara una fila por cada paleta del lote. Seleccionar cada paleta de destino antes de cargar sus JSON; luego avanzar a la tabla QC. La importación rechaza archivos conflictivos y conserva la captura anterior si falla algún JSON. Registrar los demás defectos de la muestra.
5. Evaluar, revisar motivos/cobertura y seleccionar la decisión final por muestra. Indicar inspector y confirmar; los botones permiten descargar Excel y JSON.

Para probar QC con ejemplos, carga el manifiesto dummy y selecciona una paleta; importa en ella `examples/vision/IMG_6426.json`, `IMG_6427.json` e `IMG_6428.json` y registra los demás campos. Son 36 frutos y 3 sospechas de oleocelosis que deben revisarse. Omite las paletas que no inspeccionarás. El botón **Cargar demo técnica** se retiró; sus recursos y API se conservan para pruebas técnicas.

Los datos de la demo son técnicos/simulados y no están asociados a un lote comercial. Para una inspección real, registrar sus datos y cargar sus propios JSON en la misma interfaz.

## Almacenamiento

La captura incompleta se guarda automáticamente en IndexedDB. **Guardar borrador ahora** permite solicitar el guardado y revisar el estado. Al abrir de nuevo la app se ofrece **Continuar borrador** para recuperar sus valores vacíos, recepción, JSON Vision, historial y asociaciones de lote/paleta/muestra. El lote no se abre automáticamente. Los estados provisionales del inspector se conservan como trabajo pendiente; las decisiones confirmadas y la aprobación no se recuperan: es necesario evaluar y confirmar otra vez.

Si el guardado falla o se encuentra un borrador incompatible, la app informa el problema y evita sobrescribirlo automáticamente. **Nueva inspección** descarta expresamente la captura activa y su borrador; no borra reportes ya confirmados ni el manifiesto guardado. El Excel marcado como borrador requiere una evaluación válida y no sustituye el guardado de datos incompletos.

Los reportes confirmados también se conservan en IndexedDB; el historial permite recuperarlos después de recargar. Descargar Excel y JSON conserva copias independientes. Borrar los datos del navegador elimina el almacenamiento local; otro dispositivo o un origen web distinto no lo recibe automáticamente.

El manifiesto CSV se guarda separadamente en el navegador para próximas visitas. Cada muestra conserva las filas de la paleta que se escaneó, aunque luego se cambie el archivo activo. Los campos de cajas y peso vacíos se presentan como **No registrado**.

Los datos de inspección no se envían al servidor de Sites. Los Excel completados, notebooks originales y manifiestos operativos reales permanecen excluidos de la distribución pública. El CSV dummy autorizado está disponible en `examples/reception/SmartFruit_reception_manifest_demo.csv`; se importa manualmente y no se precarga en el bundle del Site.

## Contexto y campos QC

Cada muestra presenta su lote, paleta y muestra. `image_bindings` conserva esas asociaciones fuera del JSON original de Vision y se valida antes de evaluar. La misma foto no se puede asignar a otra muestra, aunque ambas pertenezcan a una paleta; repetir un JSON idéntico en la misma muestra deja trazabilidad sin aumentar frutos.

Las etiquetas Recepción, Vision e Inspector y el listado de pendientes ayudan a revisar la captura; no son una firma ni un historial de cambios autenticado. Un cero observado es un dato registrado, distinto de un campo vacío. El resumen QC admite Label, Packing date, PLU/Coo, Open Rating y Color Rating del renglón de totales, sin deducirlos de las muestras. Ver [fidelidad del reporte](qc_fidelity.md).

## Implementación y publicación

`hosting/browser/` adapta el transporte de la interfaz y empaqueta los módulos Python mediante una lista explícita, junto con la plantilla saneada y los ejemplos técnicos. Los assets `drafts.js` y `field_sources.js` proporcionan persistencia de borrador y presentación de procedencia. Pyodide y sus dependencias se sirven desde el mismo Site. Predictive permanece OFF y no muestra indicadores en pantalla; no se ha conectado ni reentrenado ningún modelo.

La evidencia técnica y sus límites se documentan en [validation.md](validation.md). No se certificó una sesión de navegador del despliegue ni una igualdad visual o de paginación del Excel.

La app FastAPI local continúa disponible para ejecución en la máquina del servidor, con persistencia en `reports/`. Su dirección `127.0.0.1` no es el acceso que debe utilizarse desde el navegador personal en ChatGPT. El borrador activo de esa interfaz sigue siendo local al navegador.

La entrega actual añade cuatro pasos, tabla de todo el lote, precarga opcional de campos generales y vista HTML para Imprimir/Guardar PDF. Level Flag sigue requiriendo el criterio del inspector; ver [lot_workflow.md](lot_workflow.md). La instalación para trabajar desde VS Code se explica en el [README](../README.md).
