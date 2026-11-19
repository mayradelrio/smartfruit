# Fotografías de evidencia en el reporte

El QC Report en Excel y la vista imprimible muestran cantidades de fotografías, sin listar nombres de archivos, `image_id` ni `crop_id`. El historial de la primera caja y las revisiones adicionales utiliza el mismo criterio. Los JSON de inspección conservan los identificadores originales y sus asociaciones para la trazabilidad interna.

## Qué fotografías se adjuntan

La app local busca fotografías disponibles que correspondan a los resultados validados de Vision. Solo incorpora evidencia de **oleocelosis detectada**; los demás defectos siguen siendo observaciones manuales sin una clasificación fotográfica automática.

Cuando está disponible el recorte correspondiente a un fruto clasificado con oleocelosis, se adjunta ese recorte. Si existe una foto de grupo y no se puede establecer un recorte individual fiable, se presenta como **Grupo con detección**. Esto no atribuye el defecto a todos los frutos visibles. Las fotografías de frutos clasificados como sanos no se seleccionan como evidencia de oleocelosis.

Las imágenes se normalizan a JPEG de hasta 1024 píxeles por lado, sin metadatos EXIF. Los pies de foto indican paleta, caja cuando está identificada, oleocelosis y un número de fotografía; no muestran rutas ni nombres de archivo.

## Excel e impresión

- **Excel:** la hoja principal `Report` mantiene la plantilla QC. Si existen fotografías adjuntables, una hoja **Evidencia** contiene las imágenes incrustadas y sus pies de foto.
- **Vista imprimible / PDF:** las fotografías se incorporan dentro del HTML mediante imágenes de datos; no necesitan consultar una URL ni acceder de nuevo a la carpeta original. El diálogo de impresión permite guardar la vista como PDF.
- **JSON:** conserva los resultados originales, la trazabilidad y las imágenes normalizadas adjuntas. El reporte confirmado puede volver a imprimirse a partir de ese registro sin buscar otra vez los originales.

Si Vision detectó oleocelosis pero no hay fotografía disponible, el reporte indica **No se adjuntaron fotografías de los frutos con oleocelosis detectada.** La ausencia de una fotografía no cambia los conteos, los porcentajes ni la recomendación. Cuando solo parte de los frutos positivos cuenta con fotografía, el reporte identifica la disponibilidad parcial.

Una muestra sin oleocelosis no muestra un aviso de fotografías de defecto faltantes. No se genera ni sustituye evidencia con una imagen de ejemplo.

## Disponibilidad local y en navegador

El servidor local puede resolver imágenes de su catálogo Vision y de trabajos de inferencia vinculados a la inspección. Importar un JSON no incorpora por sí solo los píxeles de la fotografía; si el original correspondiente no está disponible para esa app, se conserva el resultado y se informa que no se adjuntó la foto.

El runtime exclusivamente en navegador no accede a las carpetas locales del servidor. Sus inspecciones sin archivos fotográficos resolubles mantienen el mismo aviso de disponibilidad; no intentan abrir rutas arbitrarias incluidas en un JSON.

## Contrato de presentación

Cada muestra del reporte puede contener:

```text
evidence_photos:
  - image_data_url: JPEG normalizado en base64
    sample_box_id: identificador de caja o null
    defect: oleocellosis
    view: fruit_crop o scene
    affected_fruits: cantidad positiva asociada
    width, height: dimensiones de la imagen normalizada

evidence_summary:
  status: available, partial, unavailable o no_defects
  positive_fruits, attached_fruits, attached_photos, unavailable_fruits
```

El servidor reconstruye estos adjuntos desde resultados y fuentes verificadas; no usa una imagen arbitraria enviada como supuesto adjunto final. Los exportadores aceptan únicamente imágenes raster embebidas y generan los pies de foto desde el contexto de paleta/caja. Los campos internos de evidencia no se imprimen.
