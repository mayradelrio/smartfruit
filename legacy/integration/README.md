# Integración original

`smartfruit_integration_v1.py` y `demo_smartfruit_integration.py` se conservan byte a byte. Son referencia para reutilizar reglas y agregación, no el nuevo paquete de producción.

El demo importa el módulo vecino y usa rutas absolutas `/mnt/data`. Sus tres JSON se incluyen, sin cambios, en `examples/vision/`. No se han ajustado las rutas ni ejecutado el demo durante esta organización.

Limitaciones conocidas: defectos manuales ausentes pasan a cero; se evalúan ocho de las dieciséis columnas de defectos QC; validación parcial de entradas; `attach_predictive` adjunta un valor, no ejecuta inferencia; no persiste confirmación del inspector; genera JSON, no el Excel QC real. Ver `docs/implementation_plan.md`.
