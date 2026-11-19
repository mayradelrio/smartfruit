# Rendimiento de Vision local

La app conserva un proceso separado de Vision entre tandas. El entorno web no necesita importar PyTorch; se sigue utilizando el intérprete configurado para inferencia. Los pesos se cargan con la primera inferencia y permanecen disponibles para las siguientes mientras el worker siga activo.

Los recortes individuales se clasifican en lotes de 32 por defecto. Cada imagen conserva su resultado, identidad y contexto; el progreso se actualiza por bloque terminado. La ruta de fotos completas con YOLO mantiene su comportamiento. El cambio reutiliza los pesos existentes y ejecuta la inferencia en CPU.

## Medición con los pesos reales

Prueba local con los mismos 150 recortes y pesos ResNet18, comparada contra una copia de la implementación anterior:

| Recorrido | Tiempo de inferencia |
| --- | ---: |
| Anterior, proceso nuevo y recortes individuales | 17,85 s |
| Nuevo, primera tanda con arranque y carga de pesos | 16,86 s |
| Nuevo, siguiente tanda en el mismo worker | 6,28 s |

En esta medición, una tanda con el modelo cargado fue aproximadamente **2,84 veces más rápida** que un trabajo del recorrido anterior. Es una comprobación puntual en este equipo; no garantiza ese rendimiento en otros dispositivos ni representa el tiempo total de inspeccionar una caja. Excluye selección y copia de fotos, captura manual QC y generación del reporte.

Las dos ejecuciones nuevas conservaron las 150 identidades, el orden, los conteos, las clases y los metadatos de origen. La mayor diferencia absoluta entre probabilidades fue `5.96e-8`, compatible con variaciones numéricas del procesamiento por lotes. Las dos tandas utilizaron el mismo proceso de Vision.

Los datos de medición, la solicitud, las respuestas y la copia de referencia se guardan localmente en `data/local/performance/local_worker/`, excluido de Git y del runtime del Site.

## Configuración y ciclo de vida

`SMARTFRUIT_VISION_BATCH_SIZE` acepta enteros de 1 a 128; el valor inicial es 32. La solicitud interna/CLI puede especificar `batch_size` dentro del mismo rango. Un tamaño mayor no implica necesariamente mayor velocidad y requiere más memoria. La aplicación no carga `.env` automáticamente; las variables se definen al iniciar el servidor.

El proceso se inicia cuando hace falta. Consultar disponibilidad no carga los pesos. Cerrar la aplicación termina el worker. Un fallo de protocolo, cierre inesperado, error o tiempo límite retira ese proceso; una solicitud posterior puede iniciar uno nuevo. Los trabajos fallidos se informan y no se reintentan automáticamente ni entregan resultados parciales como una inspección completa.

El CLI de una sola ejecución continúa disponible para uso manual. El Site con runtime exclusivamente de navegador conserva su flujo de QC y no ejecuta este servicio local de inferencia.
