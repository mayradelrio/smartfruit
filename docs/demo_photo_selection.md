# Fotografías de demostración por caja

El selector prepara un conjunto de **recortes individuales** acorde con `expected_count_per_box` del manifiesto. Cada recorte representa un fruto en el material de demostración. Solo se muestran los recortes asignados a la caja activa; los demás permanecen fuera del selector.

Si la caja declara 150 unidades, se ofrecen hasta 150 recortes disponibles. **Seleccionar fotos de esta caja** permite elegir el conjunto preparado sin recorrer todo el catálogo. Confirmar una tanda reduce el cupo pendiente según el conteo detectado, sin modificar los resultados de Vision ya incorporados. Finalizar la caja sigue siendo una acción expresa.

Las fotos utilizadas desaparecen de los selectores de las siguientes cajas. Los conjuntos preparados para otras cajas también quedan reservados para evitar asignaciones simultáneas. La elección es estable al actualizar el catálogo, cambiar de paleta o recuperar el borrador del mismo navegador. Incorporar o descartar una caja adicional libera sus reservas sin reutilizar las imágenes ya incorporadas.

Con 394 recortes disponibles, dos cajas de 150 pueden recibir conjuntos distintos y una tercera dispone de los 94 restantes. La interfaz informa que faltan 56 fotos para preparar esa tercera demostración; no repite imágenes para alcanzar el esperado. Los paneles de ampliación inactivos no reservan fotos.

Un manifiesto ausente, inválido o ambiguo no provoca una selección arbitraria. Primero se resuelve el conteo de la caja. Las fotografías completas con varios frutos no se consideran un fruto por imagen ni sirven para completar artificialmente este cupo: su conteo necesita inferencia.

Este comportamiento prepara datos de **demostración**, según la elección del usuario. No acredita que una caja comercial contenga las unidades declaradas ni valida faltantes de entrega: seleccionar 150 recortes conocidos prepara una población de 150 frutos. La comparación operativa de una caja real debe conservar toda su evidencia, incluidos los faltantes o sobrantes detectados.

Los reportes visibles omiten nombres de archivos e incorporan las [fotografías disponibles de los frutos con oleocelosis](photo_evidence.md).
