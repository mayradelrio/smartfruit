# Vision desde fotografías locales

El servidor local mantiene ahora el proceso de Vision entre tandas y agrupa los recortes para clasificarlos. Ver [rendimiento local y medición de 150 fotos](vision_performance.md).

La app FastAPI local puede ejecutar el clasificador entrenado y generar los JSON desde fotografías, sin entrenar de nuevo ni cargar esos JSON manualmente. El acceso privado alojado en Sites conserva su runtime de navegador: no puede leer carpetas del PC ni ejecutar PyTorch. Este flujo se usa abriendo la app local en `http://127.0.0.1:3000`.

## Archivos de entrada

```text
data/local/vision_input/
  images/    Fotografías originales o recortes individuales, conservando sus nombres
  models/
    best.pt
    resnet18_freeze_layer1_layer2_best.pth
```

Las fotografías disponibles se leen desde `images/`. El nombre no necesita contener lote ni paleta: el contexto se establece al seleccionar la paleta del manifiesto y registrar la revisión. Una fotografía del dataset no demuestra por sí sola su procedencia comercial.

Los archivos suministrados inicialmente son 394 JPG con nombres como `IMG_6419_L01.jpg`: recortes de frutos individuales, agrupados bajo 34 nombres de foto de origen. Se comprobó que los 34 nombres coinciden con `image_id` de partición `test` en el ZIP de JSON históricos, sin grupos pendientes de correspondencia. Esa comprobación usa nombres y metadatos históricos; no son etiquetas de diagnóstico del fruto.

El modo **recorte de fruto** clasifica cada imagen como un fruto y utiliza el `.pth` de ResNet18. Su agrupación por nombre de foto de origen facilita seleccionar varios recortes; no convierte cada recorte en una caja.

El modo **foto completa**, para imágenes con varios frutos, necesita también el detector YOLO y la dependencia opcional `ultralytics`. El detector localiza los frutos y el clasificador evalúa sus recortes. No se aplica ese recorrido a los recortes suministrados. Cada entrada debe representar frutos distintos: el contrato actual no identifica un mismo fruto fotografiado desde varios ángulos.

## Flujo de inspección

1. Cargar el manifiesto y abrir un lote.
2. En Vision, seleccionar una paleta y las fotografías de su primera revisión.
3. Procesar las fotografías. La app conserva el contexto de lote, paleta y muestra mientras ejecuta el trabajo en segundo plano.
4. Revisar los resultados generados y confirmarlos para incorporarlos a esa muestra. `Sample` y oleocelosis se calculan desde los JSON únicos, con las mismas validaciones de la importación existente.
5. Completar los defectos manuales y evaluar. El inspector conserva la decisión final y el Level Flag.

La demostración prepara únicamente el conjunto de recortes correspondiente al count de la caja del manifiesto. **Seleccionar fotos de esta caja** permite elegir ese conjunto; las fotos utilizadas o reservadas para otra caja no aparecen entre las opciones. Se pueden confirmar sucesivas tandas en la misma caja y el borrador conserva sus conjuntos preparados. Si el catálogo se agota, la interfaz informa cuántas fotos faltan sin reutilizar las anteriores. Ver [selección de fotografías de demostración](demo_photo_selection.md). Una toma corresponde al grupo de recortes de una fotografía original, no a una identidad comercial inferida desde el dataset.

Confirmar una tanda solo incorpora sus resultados. **Finalizar inspección de caja** confirma que se fotografiaron todos sus frutos en grupos sin solapamiento y permite evaluar QC. El progreso muestra el conteo detectado y el esperado por caja del manifiesto. Mientras la caja sigue abierta, la diferencia es parcial; al finalizar, se conservan la diferencia, la desviación y las unidades menos o más detectadas. Alcanzar el esperado no cierra la caja y una diferencia no impide finalizarla. Ver [inspección por caja](box_inspection.md).

Después del procesamiento se muestran únicamente las imágenes clasificadas con oleocelosis, con su nombre y confianza. Cada miniatura abre una vista ampliada que se puede cerrar con el botón o con Escape. La galería permanece tras confirmar los resultados. Si no hay frutos clasificados con oleocelosis se informa expresamente. Los trabajos nuevos sirven las imágenes desde sus copias de entrada, aunque después cambie la carpeta de llegada. Al recuperar un borrador anterior se pueden reconstruir las miniaturas desde el catálogo disponible y los identificadores/nombres conservados en sus resultados.

Cuando el inspector elige **EXTEND**, puede procesar otras fotografías para la caja adicional de esa paleta, también en varias tandas. Confirmar el resultado de Vision prepara sus conteos; agregar la revisión requiere finalizar esa caja y registrar sus defectos manuales. El historial conserva la primera revisión, las adicionales y el acumulado. La comparación con el manifiesto se realiza por caja, sin comparar el acumulado de dos cajas con el esperado de una.

Una imagen tiene una identidad estable a partir de su contenido. Renombrar el mismo archivo no crea un fruto nuevo. Los resultados se confirman contra el contexto con el que se creó el trabajo; cambiar de paleta mientras se procesa no debe asignarlos automáticamente a la paleta nueva.

## Entorno Python

Vision es opcional. Cargar JSON existentes y completar QC sigue funcionando con las dependencias habituales de la app. Para clasificar recortes en un intérprete compatible:

```powershell
python -m pip install -e ".[vision-crops]"
```

Para el recorrido de fotografías completas:

```powershell
python -m pip install -e ".[vision-scenes]"
```

El proceso de la web puede usar un intérprete distinto del que ejecuta Vision. Configurar `SMARTFRUIT_VISION_PYTHON` permite indicar el ejecutable que ya contiene PyTorch, torchvision y Pillow. No se descarga un modelo base ni se modifica el entrenamiento al procesar fotografías.

En el equipo de esta integración se verificaron importaciones reales con el intérprete estándar `C:\Program Files\Python314\python.exe`: PyTorch `2.12.1+cpu`, torchvision `0.27.1+cpu`, Pillow `12.2.0` y NumPy `2.4.6`. El entorno de la aplicación usa Python 3.14 con free-threading y no contiene esas bibliotecas; la ejecución separada permite reutilizar el intérprete estándar ya instalado. `ultralytics` no estaba instalado al verificar el equipo, por lo que el flujo disponible inicialmente es el de recortes.

Ejemplo de selección explícita del intérprete antes de iniciar la app, si no se detecta automáticamente:

```powershell
$env:SMARTFRUIT_VISION_PYTHON = 'C:\Program Files\Python314\python.exe'
.\.venv\Scripts\python.exe -m smartfruit.app
```

## Proceso persistente y tamaño de tanda

La app local mantiene un proceso de Vision separado y persistente. Se inicia cuando hace falta comprobar el entorno o procesar fotografías y se reutiliza entre trabajos. La consulta de disponibilidad no carga los pesos. La primera inferencia de ese proceso incluye la importación de las bibliotecas y la carga del modelo; es una ejecución **en frío**. Las tandas posteriores pueden reutilizar el modelo en memoria mientras el proceso siga activo; son ejecuciones **en caliente**.

El proceso persistente conserva modelos, no resultados de inspecciones anteriores. Cada trabajo procesa sus propias imágenes y mantiene su lote, paleta, muestra y revisión. Cerrar la app termina el proceso de Vision. Si el proceso falla, pierde la conexión o excede el tiempo de espera, el trabajo comunica el error; una petición posterior puede iniciar otro proceso. El trabajo fallido no se confirma ni se incorpora automáticamente a QC.

Los recortes individuales consecutivos se clasifican en bloques de **32 imágenes** por defecto. `SMARTFRUIT_VISION_BATCH_SIZE` permite elegir un entero entre **1 y 128** antes de iniciar la app. Un bloque reúne imágenes para una llamada del clasificador; la salida sigue siendo un JSON por fotografía, en el orden original. La primera caja y las cajas adicionales utilizan el mismo recorrido. El conteo y la confirmación de cobertura física de la caja no dependen del tamaño del bloque.

El progreso se actualiza al terminar cada bloque de recortes y cada foto completa. Durante la carga inicial del modelo o el cálculo de un bloque puede permanecer temporalmente en el mismo número. Las fotos completas mantienen su recorrido YOLO y su clasificación interna de regiones; el nuevo tamaño configurable se aplica a los recortes individuales consecutivos.

La ejecución permanece en **CPU**, con los pesos, las clases, el preprocesamiento y los umbrales existentes. No se añade entrenamiento, descarga de modelos ni selección automática de GPU. Eliminar arranques repetidos y agrupar inferencias busca reducir trabajo repetido, pero el tiempo efectivo debe medirse en el equipo de destino. Una comparación debe registrar por separado la primera ejecución en frío y las siguientes en caliente, usando las mismas fotografías y comprobando que se conservan conteos, clases y orden de salida.

Ejemplo antes de iniciar el servidor:

```powershell
$env:SMARTFRUIT_VISION_BATCH_SIZE = '32'
.\.venv\Scripts\python.exe -m smartfruit.app
```

Para una solicitud directa del CLI, `batch_size` puede incluirse como entero JSON entre 1 y 128 en el archivo de petición; tiene prioridad sobre la variable de entorno. El CLI `smartfruit.vision_inference --request ... --output ...` sigue disponible y finaliza al terminar esa solicitud: la reutilización entre trabajos corresponde al proceso que administra la app local.

## Salida y configuración

Cada trabajo guarda sus archivos bajo `data/local/vision_output/jobs/<job_id>/`: copias de las imágenes seleccionadas, petición, respuesta, estado y JSON de cada imagen. La asociación comercial queda fuera del contrato original del modelo. Los JSON mantienen `image_id`, conteos, porcentaje, confianza y predicciones por fruto.

Variables opcionales del servidor:

| Variable | Uso |
|---|---|
| `SMARTFRUIT_VISION_INPUT_DIR` | Carpeta de entrada que contiene `images/` y `models/` |
| `SMARTFRUIT_VISION_OUTPUT_DIR` | Carpeta de salida; los trabajos se guardan en su subcarpeta `jobs/` |
| `SMARTFRUIT_VISION_PYTHON` | Ejecutable Python para la inferencia |
| `SMARTFRUIT_VISION_BATCH_SIZE` | Recortes individuales por bloque del clasificador: entero de 1 a 128; valor inicial 32 |

El estado del trabajo permite distinguir cola, procesamiento, resultado disponible y error. Que un trabajo termine no confirma una inspección ni sustituye la decisión del inspector. Si faltan pesos, bibliotecas o una imagen válida, el flujo comunica el error y conserva la captura anterior. La comprobación del entorno dispone de 30 segundos de espera y una inferencia de 1800 segundos; no son estimaciones de cuánto tardará una caja. Las variables deben configurarse antes de iniciar el servidor: el archivo `.env` no se carga automáticamente.

Los pesos, fotografías y salidas permanecen en rutas locales excluidas de Git. El wrapper de inferencia reutiliza la arquitectura, las clases y el preprocesamiento de evaluación del notebook de experimentos; no se ejecutan sus celdas de entrenamiento, extracción ni borrado de carpetas.

## Comprobación con los pesos suministrados

La prueba real sobre los seis primeros recortes de `IMG_6419` produjo seis frutos y uno clasificado con oleocelosis, con confianza media `0.9915533264`. Los resultados pasaron la validación y agregación existentes. El checkpoint conserva el orden `con_oleocelosis: 0`, `sin_oleocelosis: 1`; el wrapper toma ese orden de los pesos.

También se ejecutó el CLI de inferencia desde el intérprete separado para `IMG_6419_L02.jpg`: terminó con código cero, generó su JSON y actualizó el progreso a `1/1`. La probabilidad de oleocelosis fue `0.9972288013`. La evidencia local queda en `data/local/vision_output/runtime_audit/`. Es una comprobación de ejecución y contrato; no calcula una métrica de precisión del dataset.

La prueba de interfaz se ejecutó en Chrome real con un perfil aislado. Se cargó el CSV original, se abrió el lote `5815`, se seleccionó la paleta `5645` y se procesaron sus doce recortes de `IMG_6419`: doce frutos, dos con oleocelosis. El resultado apareció pendiente antes de confirmarlo. Tras evaluar y elegir EXTEND, se procesaron doce recortes distintos de `IMG_6426`: doce frutos, uno con oleocelosis. Confirmar esa caja, registrar sus otros defectos de ejemplo en cero y agregarla produjo un acumulado de veinticuatro frutos y tres con oleocelosis (`12.5 %`), con las dos revisiones visibles en el historial.

Para llegar a la evaluación del lote en esa prueba, las otras seis paletas se completaron mediante los controles de importación de JSON históricos y defectos manuales de ejemplo en cero. No se confirmó un reporte final. Las capturas y el detalle de la prueba quedan en `data/local/browser-smoke/`; la comprobación de EXTEND no registró errores JavaScript ni errores HTTP.
