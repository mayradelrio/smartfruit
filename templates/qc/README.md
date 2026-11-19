# Plantilla QC

La plantilla vacía y la referencia pública de layout definen la estructura y presentación de la exportación. Los reportes QC completados permanecen locales y no se distribuyen con estas plantillas.

`smartfruit_qc_blank.xlsx` es una plantilla QC saneada: conserva columnas, estilos y etiquetas del formato, con datos operativos y metadatos personales eliminados. La copia empaquetada está en `src/smartfruit/resources/qc_template.xlsx`. Ambas utilizan el logo de **AgroPeru** autorizado para la personalización, tomado de `src/smartfruit/resources/branding/agroperu-logo.png`. Conservan la posición inicial y la altura del logo anterior; su ancho y extremo derecho se ajustan dentro de ese espacio para mantener la proporción del PNG. Los originales no se modifican.

La identidad AgroPeru y la etiqueta `AgroPeru Lot Number` son personalizaciones autorizadas respecto de los reportes históricos. La fidelidad de datos y layout no exige conservar literalmente la marca original. La etiqueta del lote cambia para esta entrega y conserva la clave interna `lot_id`; las restantes etiquetas del QC se mantienen. Excel y la vista imprimible obtienen el mismo logo de la plantilla empaquetada. Las pruebas separan la fidelidad de datos/layout de la nueva identidad gráfica.

`qc_report.py` reconstruye filas y totales para la cantidad de muestras recibida y agrega SmartFruit al final. Mantiene fórmulas y valores calculados para lectores que no recalculan Excel. Los tests verifican saneamiento, labels, cantidades, porcentajes, borradores, decisiones e inyección de fórmulas en texto. Ver `docs/contracts/qc_report.md`.
