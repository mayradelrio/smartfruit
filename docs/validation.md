# Verificación del MVP OFF

Entrega de guardado de borradores, asociaciones de imágenes y fidelidad del QC Report. No se ejecutaron entrenamientos, inferencia de modelos ni nuevas evaluaciones estadísticas del histórico.

## Pruebas automatizadas

| Comprobación | Resultado |
|---|---|
| Suite Python | **689 pruebas aprobadas y 2 omitidas** por permisos de enlaces simbólicos en Windows. |
| `npm test` | **146 pruebas Node aprobadas**; persistencia con `fake-indexeddb` y procedencia contextual. |
| `python -m ruff check src tests` | Aprobado. |

Estos resultados corresponden a la verificación funcional del 18 de noviembre de 2026, anterior a la limpieza de documentación. Los casos que inicialmente no pudieron preparar su directorio temporal se repitieron correctamente. Esta limpieza modifica únicamente Markdown y no ejecuta de nuevo las suites funcionales.

Las pruebas Python cubren contratos Vision, agregación, reglas y fronteras, recepción CSV, importación atómica, asociaciones, captura manual, decisiones, flag Predictive, transporte backend/browser, persistencia y exportación Excel. Las comparaciones con `legacy/` comprueban que los thresholds existentes no cambian.

Las pruebas de borrador conservan valores vacíos, JSON originales, recepción y asociaciones; comprueban que guardar o recuperar captura no restituye aprobación. También cubren errores de almacenamiento y versión, y la protección de una captura incompatible frente a sobrescritura silenciosa. `fake-indexeddb` simula IndexedDB en Node: estas pruebas no acreditan por sí solas el comportamiento de un navegador concreto.

## Verificaciones históricas de Pyodide y transporte

Se reconstruyó el bundle final y se ejecutó con Node usando Pyodide. Se comprobó lo siguiente:

- Los archivos Python seleccionados para el runtime coinciden por SHA-256 con su código fuente; `image_binding.py` está incluido.
- El manifiesto dummy autorizado se procesa como entrada local de prueba: siete registros; 5645 resuelve al lote 5815 y 5824 se rechaza porque no existe en ese archivo. El CSV no se incorpora al bundle del runtime; su copia para demo se distribuye ahora en `examples/reception/SmartFruit_reception_manifest_demo.csv`.
- `/api/vision/import` conserva el JSON original y produce asociaciones externas por imagen, muestra, paleta y lote. Repetir el mismo archivo mantiene 36 frutos; asignarlo a otra muestra devuelve 422.
- La evaluación técnica conserva 36 frutos, 3 con oleocelosis y recomendación EXPAND. El inspector puede confirmar STANDARD sin sustituir la recomendación calculada.
- Las asociaciones se conservan en el reporte. El resumen QC manual se conserva en JSON y en la fila dinámica de totales del Excel; en la prueba de una muestra es la fila 17 y permanece oculta como en el master.
- Predictive permanece OFF. Se genera el Excel sin cargar frameworks ni pesos de modelos.

Esta ejecución aporta evidencia técnica del runtime y del transporte. La asociación entre los JSON técnicos y la recepción de prueba es simulada; no se emite una inspección comercial. No se realizó una sesión gráfica de navegador ni se verificaron gestos, recargas o descargas mediante la interfaz publicada.

## Fidelidad del QC Report

La comparación con el master y los reportes reales se describe en [qc_fidelity.md](qc_fidelity.md). Comprueba datos, fórmulas, resultados, estilos semánticos y geometría del workbook, y conserva los cinco campos manuales del renglón de totales sin inferirlos desde las muestras.

La referencia versionada contiene layout y etiquetas, sin filas operativas. Los casos privados adicionales se omiten expresamente cuando no están los originales. No se verificó igualdad visual píxel a píxel ni paginación en Excel o impresora. La salida mantiene el layout de la plantilla saneada; comprobar valores de otras referencias locales no implica reproducir sus diferencias de presentación.

## Integridad, datos y publicación

Los originales privados permanecen en las rutas locales ignoradas. El bundle incluye código por allowlist, plantilla saneada y tres JSON técnicos; no contiene el CSV importado, reportes reales ni notebooks históricos. Los assets `drafts.js` y `field_sources.js` se empaquetan para la interfaz. Los assets del runtime mantienen sus hashes fijados. La exclusión del CSV en ese bundle no impide distribuir el manifiesto dummy autorizado en `examples/reception/SmartFruit_reception_manifest_demo.csv`; los Excel completados siguen privados.

La configuración, las direcciones y los identificadores de despliegues privados se mantienen fuera del repositorio público. La confirmación de un despliegue es independiente de las pruebas técnicas y no acredita una sesión gráfica del navegador.

Los reportes y borradores del Site permanecen en IndexedDB del navegador; no equivalen a los archivos `reports/` del servidor FastAPI ni se sincronizan entre dispositivos. Descargar Excel/JSON proporciona copias independientes.

## Límites

No se efectuó una validación gráfica del despliegue web. La evidencia Node/Pyodide y backend no se presenta como una certificación de la interfaz en navegador.

Las reglas cubren ocho de los dieciséis defectos registrados. No se han supuesto los mapeos restantes, la aprobación operativa de fronteras ni una política de recomendación de lote. La recomendación continúa por muestra/paleta, separada del `Level Flag` y de la decisión final del inspector. Predictive real no está conectado.

## Actualización de lote y paquete VS Code

Se verificaron descubrimiento del lote al escanear una paleta, precarga opcional real desde recepción, asociación de JSON distintos por paleta, padrón completo sin paletas repetidas/ajenas/faltantes, totales ponderados, resumen descriptivo y HTML escapado para borrador/confirmado. El cierre del lote exige Level Flag del inspector hasta definir la política automática.

La prueba Node/Pyodide usa el manifiesto dummy autorizado: escaneo 5645, lote 5815, siete paletas y siete JSON técnicos distintos (84 frutos); la asociación es simulada. Se generan Excel con siete filas y HTML imprimible tanto de borrador como de confirmado, con Predictive OFF. Los módulos del bundle se comprueban contra la fuente. No se ejecutó navegador ni se verificó paginación. La entrega incluye documentación/configuración de VS Code y un empaquetador que verifica hashes/CRC del ZIP. Para la distribución pública actual, el CSV dummy autorizado se incluye en `examples/reception/SmartFruit_reception_manifest_demo.csv`; los Excel completados y los demás originales privados permanecen excluidos.

Se verificó un paquete de código y documentación que incluye el logo activo y el manifiesto dummy. Los únicos Excel incluidos son las dos plantillas vacías; quedan fuera los reportes completados, datos locales, entornos y recursos de identidad anteriores. La comprobación del paquete no acredita por sí sola una sesión gráfica del navegador.
