# Ejemplos existentes

- `reception/SmartFruit_reception_manifest_demo.csv`: manifiesto **dummy**, autorizado por el propietario para ejecutar la demostración de recepción. Se carga manualmente desde la interfaz; no incluye los reportes Excel completados.

- `integration/demo_smartfruit_report.json`: salida de demostración original. Sus identificadores `LOT_DEMO_001`, `PALLET_DEMO_01` y `SAMPLE_DEMO_001` son de demo.
- `vision/IMG_6426.json`, `IMG_6427.json`, `IMG_6428.json`: bytes originales extraídos del ZIP. Tienen `partition=test` y corresponden a las imágenes usadas por el script de demostración.

Son una muestra técnica: 36 frutos, 3 clasificados con oleocelosis y 8,3333 %. No existe evidencia para asociarlas a un pallet real, al manifest ni a los lotes de los dos Excel. Su inclusión no implica ejecutar otra evaluación del modelo.

El JSON de demo es una referencia existente, no el diseño final del QC Report. Incluye `predicted_loss_pct: null` con Predictive OFF; la presentación final deberá omitir ese campo cuando esté apagado, conforme a la solicitud del usuario.

## Caja adicional simulada

`vision/DEMO_ADDITIONAL_BOX_001.json` es un ejemplo ficticio nuevo para probar **EXTEND**. Contiene 12 frutos y 2 casos de oleocelosis; `data_origin=SIMULATED_DEMO` identifica su procedencia. No es uno de los JSON originales ni una salida nueva del modelo. Carga el manifiesto dummy y los JSON de ejemplo en una paleta, evalúa y elige **EXTEND**; importa este archivo como caja adicional y registra sus defectos manuales. La asociación es simulada. El botón **Cargar demo técnica** ya no aparece; los recursos y la API de demo siguen disponibles para pruebas. Consulta el [flujo de revisiones adicionales](../docs/additional_reviews.md).
