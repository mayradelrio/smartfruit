# Notebooks de SmartFruit

## Auditoría de datos E4

La [carpeta de auditoría](auditoria/README.md) contiene `SmartFruit_E4_Auditoria_Final.ipynb`, incorporado por solicitud del usuario como documento de auditoría de acceso, calidad y evidencia frente a las hipótesis del proyecto. Se conserva la copia íntegra entregada, incluidas sus salidas guardadas. No se ejecutó ni se modificó para incorporarlo al repositorio.

## Notebooks originales de modelos

La entrega local conserva ambos notebooks en `originals/`, con sus nombres y bytes originales. Esa carpeta está excluida de Git porque las salidas guardadas contienen datos históricos de negocio.

- `SmartFruit_Baseline_Experimentos_Comparativos.ipynb`: experimentos de Vision.
- `SmartFruit_Predictive_v4_BusinessSeverity.ipynb`: análisis predictivo y reglas de severidad.

Durante la integración no se han ejecutado, limpiado ni refactorizado estos notebooks, ni se han reentrenado sus modelos. La aplicación reutiliza los pesos existentes mediante módulos Python. Un clon de Git no incluye los notebooks; el paquete privado completo para VS Code puede conservar los originales según su inventario. No forman parte del runtime publicado del Site. No se adjuntó un artefacto Predictive entrenado para inferencia.

La instalación y el recorrido de la app están en el [README](../README.md). La integración se describe en [arquitectura](../docs/architecture.md) y el alcance predictivo en [Predictive experimental](../docs/predictive.md).
