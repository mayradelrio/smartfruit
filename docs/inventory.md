# Inventario de recursos y procedencia

El repositorio público contiene el código del MVP, sus pruebas, documentación técnica y recursos autorizados para ejecutar la aplicación y su demo. Los originales operativos, reportes completados, fotografías de trabajo, datasets completos y notebooks con outputs históricos se conservan localmente.

## Recursos públicos

| Recurso | Ubicación | Uso |
|---|---|---|
| Código de la aplicación | `src/smartfruit/` | Captura QC, reglas, revisión del inspector y exportación |
| Pruebas y referencia de layout | `tests/` | Contratos, comportamiento, fórmulas y presentación sin publicar inspecciones reales |
| Plantilla QC vacía | `templates/qc/smartfruit_qc_blank.xlsx` | Formato base de exportación, sin datos operativos ni metadatos personales |
| Plantilla y recursos empaquetados | `src/smartfruit/resources/` | Plantilla vacía, identidad AgroPeru y JSON de la demo técnica |
| JSON de demostración | `examples/vision/` | Ejemplos técnicos de Vision y una caja adicional explícitamente simulada |
| Manifiesto dummy autorizado | `examples/reception/SmartFruit_reception_manifest_demo.csv` | Carga manual de CSV y selección de lote/paleta de demostración |
| Ejemplo de integración | `examples/integration/` | Salida técnica identificada como demo |
| Código de referencia | `legacy/integration/` | Comparación de reglas; el script de demo histórico usa rutas no portables |
| Documentación | `docs/` | Arquitectura, contratos, límites y funcionamiento del MVP |

La demo técnica utiliza tres JSON de evaluación con datos de inspección simulados y sin asociación comercial acreditada. No necesita fotografías ni pesos locales. El manifiesto dummy es una entrada separada que el usuario importa manualmente; no representa una recepción comercial.

## Recursos locales excluidos

| Categoría | Ubicación local | Motivo de exclusión |
|---|---|---|
| Originales QC/IMP y otros adjuntos de trabajo | `data/local/` | Pueden contener información operativa o privada |
| Fotografías, modelos y trabajos de Vision | `data/local/` | Material y salidas locales fuera de la demo JSON pública |
| Notebooks originales con outputs | `notebooks/originals/` | Referencias históricas que pueden contener datos del negocio y rutas locales |
| Reportes confirmados y captura original | `reports/` | Datos de cada inspección, observaciones e imágenes adjuntas |

El inventario privado `docs/source_inventory.json`, cuando está disponible localmente, conserva nombres originales, rutas, tamaños y SHA-256 para comprobar la integridad de los adjuntos. Está excluido de Git y no es necesario para ejecutar la demo pública. No se publica su contenido ni se exige disponer de los originales privados para usar el MVP.

## Alcance de la validación

Las pruebas públicas verifican el layout de referencia, los contratos y el comportamiento con datos técnicos o sintéticos. Las comparaciones adicionales con originales privados se omiten cuando no están disponibles. Comprobar estructura, fórmulas y estilos no certifica igualdad visual píxel a píxel ni paginación idéntica en Excel o impresora.
