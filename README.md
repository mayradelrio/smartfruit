# SmartFruit para AgroPeru

MVP de apoyo a la inspección de calidad de limones para AgroPeru. Integra recepción por manifiesto CSV, resultados de Vision, captura manual QC, recomendaciones por paleta y reportes Excel/JSON con revisión del inspector.

Esta versión conserva el estado actual del MVP antes de implementar feedback de usuarios. La decisión final corresponde al inspector. **Predictive está OFF por defecto**; el recorrido principal funciona con reglas y no necesita un modelo predictivo.

## Requisitos

- Python 3.10 o superior.
- Un navegador para abrir la aplicación local.
- Node.js y npm únicamente para ejecutar las pruebas del cliente.
- PyTorch y pesos locales solo si se quiere generar resultados desde fotografías.

Ejecuta los comandos desde la carpeta que contiene `pyproject.toml` y este README.

## Instalación y ejecución

### Windows — PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
$env:USE_PREDICTIVE = 'False'
python -m smartfruit.app
```

Si Python no dispone de la zona horaria `America/Lima`, instala su base de datos con `python -m pip install tzdata`.

### macOS / Linux — shell POSIX

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
export USE_PREDICTIVE=False
python -m smartfruit.app
```

Abre **http://127.0.0.1:3000** en el mismo equipo. Mantén el servidor encendido mientras usas la aplicación. El comando `smartfruit` es un punto de entrada equivalente.

## Primera prueba: demo técnica

1. Pulsa **Cargar demo técnica**. Se cargan tres JSON de Vision existentes y datos manuales simulados.
2. Revisa los resultados y completa los campos pendientes de la inspección.
3. Evalúa la captura y revisa la sugerencia de cada paleta. La demo inicial contiene 36 frutos y 3 con oleocelosis.
4. Para ensayar una ampliación, elige **EXTEND** y carga `examples/vision/DEMO_ADDITIONAL_BOX_001.json`. Contiene 12 frutos ficticios, 2 con oleocelosis.
5. Revisa el reporte, registra el inspector y sus decisiones y confirma expresamente cuando corresponda. Puedes descargar Excel/JSON y abrir la vista imprimible.

Esta demo usa JSON incluidos en el paquete: **no necesita fotografías, datasets completos, pesos, PyTorch ni acceso a sistemas de AgroPeru**. Los JSON de Vision de evaluación no acreditan su asociación a un lote comercial; el contexto y los defectos manuales de la demo son simulados.

Para ensayar la recepción, carga manualmente `examples/reception/SmartFruit_reception_manifest_demo.csv` y selecciona el lote y la paleta en la interfaz. Este manifiesto dummy autorizado es un ejemplo de demostración, separado de los tres JSON del botón; no debe confundirse con un manifiesto operativo. La demo técnica del botón funciona también sin cargar un manifiesto.

## Flujo de inspección

```text
Manifiesto CSV → lote y paletas → Vision JSON o inferencia local opcional
              → captura manual QC → reglas → revisión del inspector
              → reporte Excel/JSON y vista imprimible
```

Al cargar un manifiesto, selecciona el lote, revisa sus paletas y vincula los resultados de Vision a la caja correspondiente. `Sample` y oleocelosis proceden de los JSON únicos; los otros quince defectos se registran manualmente. Confirma que la caja está completamente inspeccionada antes de evaluarla. Una ampliación conserva el detalle de las cajas y recalcula el acumulado de la paleta.

El navegador conserva el borrador en IndexedDB. Recuperarlo exige evaluar de nuevo y volver a confirmar las decisiones. El guardado automático no confirma reportes ni sustituye una copia de seguridad.

## Vision desde fotografías — opcional

Para clasificar recortes individuales:

```sh
python -m pip install -e '.[vision-crops]'
```

Para fotografías completas con detección y clasificación:

```sh
python -m pip install -e '.[vision-scenes]'
```

Prepara los archivos locales con esta estructura:

```text
data/local/vision_input/
  images/    Fotografías o recortes para procesar
  models/
    resnet18_freeze_layer1_layer2_best.pth
    best.pt
```

El clasificador `.pth` se necesita para los recortes; el detector `best.pt` se añade para fotografías completas. Los pesos deben proceder de los artefactos autorizados del proyecto y ser compatibles con el preprocesamiento implementado. La aplicación ejecuta inferencia con los pesos existentes; no reentrena ni descarga modelos automáticamente. Los modelos, datasets y fotografías locales no forman parte del repositorio público.

Los trabajos de Vision generan copias de entrada, contexto y JSON en `data/local/vision_output/jobs/`. La carga manual de JSON sigue disponible sin instalar estos extras.

## Configuración

`.env.example` documenta variables opcionales. **La aplicación no carga `.env` automáticamente**: define las variables en la terminal antes de iniciar el servidor.

| Variable | Valor inicial / función |
| --- | --- |
| `PORT` | `3000`; el servidor escucha en `127.0.0.1` |
| `USE_PREDICTIVE` | `False`; acepta `False` o `True` |
| `SMARTFRUIT_REPORTS_DIR` | `reports`; carpeta de reportes confirmados |
| `SMARTFRUIT_VISION_INPUT_DIR` | `data/local/vision_input`; contiene `images/` y `models/` |
| `SMARTFRUIT_VISION_OUTPUT_DIR` | Carpeta `vision_output` junto a la entrada; contiene `jobs/` |
| `SMARTFRUIT_VISION_PYTHON` | Intérprete opcional que tenga instaladas las dependencias de Vision |
| `SMARTFRUIT_VISION_BATCH_SIZE` | `32`; admite enteros de 1 a 128 |

Con `USE_PREDICTIVE=True`, la interfaz identifica Predictive como experimental. En esta versión no hay un artefacto predictivo conectado: informa indisponibilidad y conserva la evaluación por reglas; no fabrica una predicción de pérdida.

## Archivos del proyecto

```text
src/smartfruit/          Código Python, interfaz y recursos necesarios del MVP
src/smartfruit/resources/ Plantillas vacías y JSON técnicos empaquetados
tests/                 Pruebas Python y JavaScript
examples/               JSON de demostración y ejemplos de integración
templates/qc/          Plantilla QC vacía y documentación de su formato
docs/                   Arquitectura, contratos, funcionamiento y límites
legacy/integration/     Referencia histórica utilizada para comprobar las reglas
hosting/browser/        Adaptador para ejecutar la lógica QC en el navegador
scripts/                Herramientas de empaquetado
data/local/            Archivos locales y resultados de Vision; ignorados
notebooks/originals/    Notebooks históricos con outputs; ignorados
reports/                Reportes generados; ignorados
```

Las plantillas QC vacías son recursos necesarios para exportar reportes y se versionan. Conservan el formato y las fórmulas, sin filas operativas completadas. Los reportes de una inspección son archivos distintos: al confirmar se crean `report.xlsx`, `report.json` y `source.json` en `reports/<id>/`; no se versionan. Fotografías adjuntas, recepción, nombres y observaciones de una inspección pueden quedar dentro de estos reportes.

Los entornos virtuales, cachés, dependencias instaladas, originales QC/IMP, datasets completos, pesos y salidas generadas se conservan fuera del historial público mediante `.gitignore`. El manifiesto dummy autorizado se distribuye en `examples/reception/SmartFruit_reception_manifest_demo.csv`, identificado como ejemplo.

## Verificación

Con el entorno Python activado:

```sh
python -m pytest -q
python -m ruff check src tests
npm ci
npm test
```

Las pruebas JavaScript usan Node.js y `fake-indexeddb`. Algunas comparaciones con originales privados se omiten si esos archivos no están disponibles; los originales no son requisito para ejecutar la demo técnica. `legacy/integration/smartfruit_integration_v1.py` se mantiene como referencia para las pruebas de reglas; su script de demo histórico no es el punto de entrada de la aplicación.

## Límites del MVP

- Vision automatiza oleocelosis; el resto de defectos requiere inspección manual.
- Se capturan dieciséis defectos y las reglas actuales evalúan ocho. La interfaz informa los que todavía no tienen regla.
- Las sugerencias se calculan por muestra/paleta. El `Level Flag` y la decisión final permanecen a cargo del inspector.
- Los identificadores de imagen evitan contar el mismo JSON dos veces; no reconocen un fruto repetido en fotografías diferentes.
- La confirmación registra nombre, decisión y fecha; no implementa autenticación de identidad ni firma criptográfica.
- La persistencia es local. No hay conexión en vivo al sistema de recepción ni sincronización entre equipos. Descarga los reportes para conservar copias independientes.
- La exportación mantiene la estructura QC, pero no certifica una paginación idéntica en todas las versiones de Excel, navegadores o impresoras.
