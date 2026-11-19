# Predictive experimental

El notebook adjunto analiza pérdida posterior a nivel de lote usando señales del primer QC. Incluye regresiones Ridge, transformaciones y evaluación Leave-One-Lot-Out; no es un endpoint de inferencia desplegado.

Las features de contexto de v4 son `sample_count_total`, `n_pallets`, `avg_count_per_box_mean` y `pulp_temp_mean`. Las variantes añaden oleocelosis, carga de defectos o features de Business Severity. La unidad de inferencia no se debe cambiar de lote a fotografía o muestra por conveniencia.

Las métricas y salidas históricas del notebook se conservan únicamente en las fuentes locales excluidas de Git. No constituyen una validación independiente ni una garantía de rendimiento del MVP.

No se adjunta un artefacto entrenado exportado. El notebook contiene entrenamiento; ejecutarlo para obtener un modelo sería reentrenar y queda fuera del alcance autorizado. `attach_predictive()` solo incorpora un `predicted_loss_pct` proporcionado por otro componente.

## Adaptador implementado; modelo sin conectar

- `USE_PREDICTIVE=False` como valor inicial. No cargar pesos ni dependencias predictivas.
- Con `True`, mostrar ON - Experimental y usar exclusivamente el modelo, preprocesamiento, features y unidades correspondientes al artefacto existente que se proporcione.
- `predicted_loss_pct` es una señal adicional y solo se presenta con ON.
- Un artefacto ausente, datos insuficientes o un error de inferencia no bloquean el recorrido basado en reglas. No simular una predicción ni sustituir un fallo por cero.
- No introducir thresholds de pérdida para cambiar recomendaciones. Los cortes exploratorios del notebook no son reglas operativas aprobadas.

Antes de conectar ON se necesita el artefacto existente, su preprocesamiento, esquema/orden de features, unidad y escala del output y versiones de dependencias. Nada de ello obliga a posponer el MVP OFF.

`predictive.py` permite un proveedor inyectado para probar el aislamiento. La aplicación no conecta ninguno: incluso con `USE_PREDICTIVE=True` informa indisponibilidad sin fabricar una predicción. No se ha implementado inferencia real por lote ni seleccionado automáticamente una variante del notebook.
