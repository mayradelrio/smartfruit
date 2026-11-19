# Plan y pendientes

## Paso 1 — Organización (completado)

- Preservar los adjuntos privados y sus hashes en un inventario local excluido de la publicación.
- Separar código de referencia, futuros módulos, ejemplos, datos operativos y notebooks.
- Inicializar Git local y documentar contratos, reglas y limitaciones.
- Verificar que los originales se conservan y que los datos excluidos no están en el índice de Git.

Los originales se preservan sin alteración; código nuevo separado de `legacy/`.

## Paso 2 — MVP con Predictive OFF (implementado)

1. Crear agregación y validación en el paquete, reutilizando el contrato actual; probar deduplicación y cantidades.
2. Crear captura con los campos QC reales, cantidades manuales, asociación de fotos y denominadores explícitos.
3. Reutilizar reglas y política de frontera existente; probar valores límite y entradas inválidas.
4. Separar recomendación calculada y decisión humana; guardar confirmación y observaciones.
5. Preparar una plantilla sin datos históricos basada en los Excel y generar el QC Report digital con sección SmartFruit.
6. Validar el recorrido completo OFF sin modelos ni dependencias de entrenamiento.

La interfaz y el Excel muestran recomendaciones por muestra/pallet. La cobertura completa de Sample se confirma explícitamente; los conteos manuales pendientes bloquean la evaluación hasta registrarse. Se detectan conflictos de contenido bajo un mismo `image_id`, y se rechaza asignar una imagen a muestras diferentes del mismo reporte.

La actualización de captura añade borrador recuperable en el mismo navegador, contexto visible y validación al importar las imágenes, indicación de procedencia/pendientes y resumen manual del renglón de totales. Recuperar un borrador no recupera la aprobación: exige reevaluación y nueva confirmación. La exportación se contrasta con una referencia saneada y, opcionalmente, con originales privados locales; ver `qc_fidelity.md` para el alcance y los límites de presentación.

## Entrada operativa implementada — manifiesto del checker

El proceso de recepción actual revisa la mercancía, registra la distribución por paleta y genera/coloca las etiquetas internas. Esto lo realiza el checker antes de iniciar QC, tanto para packing list como para OC.

La interfaz antepone la carga del manifiesto CSV y el escaneo del número de paleta o código completo, con precarga de datos conocidos y procedencia por muestra. El CSV se conserva en el navegador y se puede reemplazar sin modificar muestras ya iniciadas. No se generan nuevos números de paleta ni etiquetas. Sigue pendiente una consulta en vivo al sistema actual; el MVP usa la importación autorizada del CSV existente. Ver `reception.md`.

## Paso 3 — Predictive ON (sin conectar el modelo)

Conectar el artefacto existente y sus transformaciones mediante el adaptador experimental. No reentrenar. Probar que su fallo no altera ni impide el recorrido de reglas.

## Pendientes que no se deben resolver por suposición

| Tema | Evidencia y tratamiento necesario |
|---|---|
| Alcance de la muestra | Implementado: asociación explícita y misma población Vision/Sample. Una futura cobertura parcial requiere definir su tratamiento con QC. |
| Fronteras exactas | Mantener `higher` como referencia de demo y declarar la política; confirmar antes de uso operativo. |
| Dieciséis defectos frente a ocho reglas | Conservar captura completa; documentar criterios de la imagen y confirmar equivalencias ambiguas antes de ampliar el mapa. |
| Severidad de muestra/lote | Implementado por muestra y separado de `Level Flag`. Una política de recomendación de lote sigue pendiente de definición del negocio. |
| Captura incompleta | Resuelto: los quince defectos manuales deben registrarse explícitamente, también los ceros. |
| Conflicto de duplicados | Resuelto: duplicados idénticos se ignoran y trazan; contenido distinto con el mismo `image_id` genera error de validación. |
| Motivo de STANDARD | Implementado: explicación explícita limitada a los ocho defectos con regla. |
| QC y normalización | PLU y Pulp tienen valores heterogéneos; conservar fuente, confirmar interpretación antes de transformar. |
| Datos del manifest | La copia pública es dummy autorizada; no vincularla automáticamente a los Excel privados ni a las fotos de evaluación. |
| Artefacto Predictive | No está adjunto; ON real depende de recibirlo con su preprocesamiento y contrato. |

Estos pendientes no requieren reentrenamiento ni rediseño del JSON de Vision. La arquitectura y las partes independientes del MVP OFF pueden avanzar sin inventar sus respuestas.
