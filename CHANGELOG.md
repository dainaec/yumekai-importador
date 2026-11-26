# Cambios de Yumekai

Las novedades en desarrollo se registran en Sin publicar hasta preparar su distribución. La versión del programa se define en yumekai_importer/version.py.

## [Sin publicar] · 26/11/2026

### Añadido

- Eliminación selectiva o completa de las recuperaciones locales desde Ayuda y registros, disponible sin conexión.
- Limpieza de pendientes, revisiones archivadas, propuestas SD de tienda, ediciones manuales, creaciones pendientes y temporales.
- Inicio con el logo SVG de Yumekai y tres accesos independientes.

### Mejorado

- Búsqueda con espera de 200 ms tras la última pulsación y reutilización de las filas cargadas.
- Sincronización de las filas filtradas con las columnas fijas y las casillas.
- Lectura de los controles de filtro fuera del recorrido de cada ficha y omisión de filtros vacíos.
- Equivalencias de temática SD acordadas; diferencias de clasificación y autoría propuestas para revisión.
- Autoría múltiple de SD separada por /.
- Búsqueda por equivalentes válidos de ISBN-10 e ISBN-13, verificando el código de la ficha principal.
- Revisión de colección/tomo por diferencias, con limpieza de sufijos COMIC, tomos intermedios, tomo por defecto y rangos de packs.
- Limpieza de la pantalla tras guardar cargas completas sin incidencias pendientes.

### Corregido

- Sustituido el cruce automático con WooCommerce por Comprobar productos ya subidos, ejecutado expresamente tras importar en la tienda.
- Separación entre Actualizar lista y el cruce con WooCommerce.
- Normalización de códigos numéricos con guiones o espacios, incluidos ISBN-10 y códigos largos admitidos.
- Propuestas de autoría y clasificación que antes se conservaban sin ofrecer la diferencia al existir un valor previo.
- Descarte en memoria de las recuperaciones eliminadas para impedir que vuelvan a guardarse al cerrar.
- Aviso de limpieza incompleta y conservación del estado de las recuperaciones cuya eliminación falla.
- Restaurada la inicialización de _api_override en InventoryWindow para cargar Productos en tienda.

### Distribución y validación

- La limpieza local conserva el catálogo del servidor y no revierte creaciones ya completadas.
- La normalización de códigos no renombra automáticamente todos los registros históricos.
- Validar la integración y el ejecutable Windows antes de publicar una nueva versión. Esta entrada no declara una versión distribuida ni una ejecución completa de todas las pruebas.

## 0.3.1 · 25/11/2026

- Jerarquía visual compartida de botones principales, secundarios, de consulta y retirada; cuadros de confirmación en español.
- Casillas grandes iguales en tienda, pendientes y revisiones; avisos y cabeceras de diálogo comunes.
- Colección/tomo utiliza la misma revisión por campos que SD y guarda lo aceptado sin abrir una segunda revisión equivalente.
- Se elimina el menú técnico de tienda y la recarga duplicada. Actualizar tienda vuelve a consultar WooCommerce; Recuperar revisión solo aparece cuando hay una copia local.
- Cruce automático con WooCommerce antes de cargar ambas listas de revisión. También reconoce borradores, privados y pendientes de publicación. Una recuperación local no reintroduce fichas ya retiradas de esas listas.
- Identificación por el ISBN real, con respaldo de GTIN o SKU YMK cuando falta el campo personalizado. Nunca se vincula por parecido del título.
- Confirmación de publicación con ID/título/ISBN y acceso a la URL exacta del producto.
- Verificación del estado en la base de datos antes y después de COMMIT; invalidación de WordPress/WooCommerce y solicitud de purga de producto/URL a W3 Total Cache después de confirmar el guardado.
- Las peticiones a la API evitan cachés persistentes. Se precargan también los posts de adjuntos para reducir las consultas de portadas.
- API de catálogo versión 3: la aplicación avisa si faltan los PHP de esta actualización.
- Se mantienen el endpoint y los setters del guardado SD validado.

## 0.3.0 · 25/11/2026

Preparada a partir de `ymk_importer.zip`, conservando el endpoint de guardado SD validado por la usuaria.

- Lectura paginada del catálogo de WooCommerce: publicados, borradores y todo el catálogo (incluidos privados y pendientes, sin papelera).
- El tipo de obra sigue las categorías actuales y sus padres, incluso la grafía `Manwha`. `_yk_item_kind` queda como respaldo cuando no hay categoría reconocida. Se informa de categorías contradictorias.
- La tabla muestra los datos guardados; las propuestas SD se mantienen separadas hasta su aceptación.
- Progreso, tiempo transcurrido y cancelación de lectura. Se conserva la lista anterior ante error o cancelación. Dos peticiones simultáneas, 200 productos por página, cachés de WordPress precargadas por lote.
- Registro de tiempos del servidor, red y construcción de tabla; se mantiene la lectura al volver desde Inicio y se actualiza con Recargar.
- Nuevo producto simple como borrador, SKU sugerido `YMK-código`, selección expresa de impuesto y recuperación de una creación sin confirmar mediante el mismo identificador persistente.
- Edición manual de fichas simples: título, ISBN/referencia con desbloqueo, SKU, datos bibliográficos, precios independientes, estado, destacado, impuesto, categorías y descripciones. Consulta de datos recibidos y metadatos en una pestaña; recuperación de ediciones manuales sin confirmar.
- Despublicar pasa a borrador y conserva ID y datos. Publicar restaura el mismo producto tras confirmación.
- Validación de versión antes de escribir, resultados individuales por producto y detención de lotes tras un resultado sin confirmar.
- `build.ps1` conserva las opciones de compilación facilitadas y añade registro de consola y comprobación del ZIP generado.

Pruebas locales: Python/Qt, PHP con WordPress/WooCommerce simulados y transacciones SQLite; no sustituyen la comprobación contra Hostalia. El ejecutable Windows debe compilarse en Windows.

---

## Notas históricas de desarrollo

Todos los cambios relevantes del importador y gestor de catálogo de Yumekai se documentan en este archivo.

El siguiente bloque conserva notas históricas del 25/11/2026; sus limitaciones describen ese estado anterior, no el funcionamiento actual.

### Estado de desarrollo · 25/11/2026

Estado de desarrollo documentado a 2026-11-25. Incluye las actualizaciones de excepciones, disponibilidad SD y revisión de productos publicados. La conexión de escritura con la tienda está implementada y probada localmente; su comprobación real en Hostalia está pendiente.

### Añadido

- Espacio de revisión con las secciones Preparar fichas y En tienda; el acceso Productos en tienda del inicio abre esta misma sección.
- Lectura de los productos publicados directamente desde WooCommerce, con los valores actuales de sus fichas.
- API propia de consulta y actualización de tienda mediante `store_review.php` y `store_common.php`, sin cambios en el plugin de la web.
- Propuestas de actualización por campo, con comparación entre Actual y Propuesto y posibilidad de aceptar o descartar valores individuales.
- Comparación de textos completos mediante doble clic en los valores del diálogo de revisión.
- Actualización desde el programa de disponibilidad, sinopsis y datos bibliográficos/comerciales admitidos de productos simples publicados.
- Identificación de productos publicados por ID de WordPress, aunque se repita el ISBN.
- Modo Solo disponibilidad dentro de la recomprobación SD, separado de la revisión completa de la ficha.
- Formateo de sinopsis integrado en la revisión completa: unión de saltos simples dentro de un párrafo y conservación de las separaciones entre párrafos.
- Detección de HTML, listas reconocibles, diálogos con guion y palabras partidas para conservar el formato y avisar de revisión manual.
- Permisos por ficha para importar códigos fuera del estándar ISBN-13 y PVP pendiente, mediante selección manual y una segunda confirmación antes del envío.
- Admisión de códigos no estándar de hasta 128 caracteres, incluidos códigos largos y ceros iniciales, conservados como texto.
- Autorización explícita de avisos al pasar a Listas para subir: código, título y estado Yumekai como únicos campos obligatorios.
- Copia local `store-recovery.json` para propuestas sobre productos publicados, independiente de `review-recovery.json`.
- Comprobación de versiones de las fichas de tienda antes de aplicar cambios, incluyendo diferencias dentro del mismo segundo.
- Resultados por producto y envío de actualizaciones de tienda en lotes de 20.

### Mejorado

- Centralización de la consulta a distribuidores en Revisar.
- Reutilización de las reglas SD para fichas nuevas y productos ya publicados.
- Uso de la sinopsis actual como base del formateo, conservando las ediciones manuales y mostrando las propuestas antes de aplicarlas.
- Extracción de sinopsis SD con conservación de los límites de párrafo y del contenido con formato semántico.
- Conservación de los cuatro estados Yumekai completos, incluido `yk_on_demand`, al leer y actualizar productos publicados.
- Conservación de campos desmarcados como propuestas pendientes después de un guardado parcial.
- Guardados independientes: una ficha con un conflicto conocido no impide guardar las demás fichas elegibles.
- Recuperación local con los datos y la versión originales para detectar cambios posteriores del servidor.
- Detención de envíos ante desconexiones o resultados sin confirmar, conservando las propuestas pendientes.
- Normalización de formatos: variantes de Cartoné a Tapa dura; valores vacíos o de clasificación a Rústica; conservación de otros formatos válidos de SD.
- Equivalencias de clasificación SD, incluyendo Yaoi / BL, Spokon, Manga adulto, Terror, Artbooks/novelas y Yuri.
- Comprobación previa al CSV con avisos y opciones para devolver fichas a revisión o generar el archivo con los datos disponibles.
- Exportación de códigos completos y precios ausentes vacíos, sin sustituirlos por identificadores recortados o precios inventados.

### Corregido

- Rechazo de códigos reales del distribuidor por no cumplir el estándar ISBN-13.
- Restricciones de longitud del identificador en las validaciones de importación, revisión y consulta; ajuste de esquema previsto mediante `ampliar_codigos_productos.sql` para instalaciones anteriores.
- Bloqueo del paso a listas por datos opcionales incompletos: ahora se pueden autorizar expresamente los avisos.
- Interpretación de Sin stock como Sin existencias y de Consultar disponibilidad según la fecha de publicación y el día de consulta.
- Inferencia de falta de existencias a partir de consultas fallidas, productos no encontrados o fechas necesarias sin confirmar: esos casos conservan el estado anterior.
- Reutilización de detalles SD en caché durante una nueva comprobación de disponibilidad.
- Confusión entre fecha de publicación, fecha de última actualización y datos de productos relacionados al interpretar una ficha SD.
- Recuperación de sinopsis recortadas cuando SD contiene una ampliación del mismo comienzo del texto guardado.
- Formato de la etiqueta simple Rústica y conversión de valores de demografía o tipo de obra usados como encuadernación.
- Escritura de Shōjo en categorías del CSV: se exporta como Shojo, conservando la etiqueta de la interfaz.
- Vinculación de referencias de WordPress con códigos no estándar y SKU antiguos.

### Retirado

- Botón Comprobar stock y fichas SD de la pantalla Importar. La consulta se realiza desde Revisar.

### Validación

- 214 pruebas automatizadas locales superadas en el estado de desarrollo del 25/11/2026.
- Comprobación de sintaxis PHP y compilación de los módulos Python.
- Pruebas de lectura Excel, códigos no estándar, permisos manuales, reglas de stock, sinopsis, CSV, selección por campo, cancelación y recuperación local.
- Pruebas de la API PHP con un sustituto local de WordPress/WooCommerce para verificar actualizaciones selectivas, conflictos y guardados parciales.
- Pruebas del paquete de actualización aplicado sobre una copia limpia del código proporcionado.
- Sin comprobación de escritura en la tienda real desde este entorno; pendiente de validación inicial en Hostalia.

### Despliegue y compatibilidad

- Copiar los archivos actualizados del programa y recompilar si se distribuye el ejecutable.
- Subir `store_common.php` y `store_review.php` a la carpeta protegida `importer-api`, junto a `review_common.php` y `exception_rules.php` de la API existente.
- Mantener la protección Basic Auth y HTTPS de la API propia.
- WordPress debe disponer de `wp-load.php` en la carpeta superior a `importer-api`, igual que en la sincronización existente.
- Las instalaciones con columnas cortas deben aplicar el ajuste de códigos en la base del importador: `isbn VARCHAR(128)` y `sku VARCHAR(160)`. La nueva conexión de tienda no añade otra migración SQL.
- Los cuatro estados Yumekai deben estar reconocidos por la instalación existente de WooCommerce. La actualización no modifica el plugin que los registra.

### Limitaciones conocidas

- La actualización directa está preparada para productos simples publicados. No crea ni elimina productos ni actualiza borradores o variaciones.
- Los productos que gestionan cantidades no pierden esa gestión: si impide aplicar el estado se informa de una incidencia.
- Esta conexión no cambia títulos, ISBN, SKU, categorías, demografías, portadas o CSS de productos publicados.
- Las consultas a distribuidores distintos de SD siguen pendientes.
- La comprobación de tienda se inicia manualmente; no hay una sincronización periódica desatendida.
- Los textos con formato especial se conservan para revisión manual.
- La interfaz utiliza credenciales previamente guardadas mediante keyring; todavía no incorpora un asistente de configuración de acceso.
- El ejecutable sigue sin firma digital.

## [0.1.0] - 2026-11-24

Primera versión de distribución interna de Yumekai.

### Añadido

- Pantalla principal de gestión del catálogo.
- Importación de catálogos mediante archivos Excel.
- Validación de ISBN y detección de incidencias.
- Gestión centralizada de fichas mediante la API de Hostalia.
- Pantallas de productos pendientes de revisión y listos para subir.
- Edición de fichas de productos.
- Búsqueda y filtros avanzados.
- Detección de títulos duplicados.
- Revisión de colecciones y números de tomo.
- Consulta de disponibilidad e información en SD Distribuciones.
- Exportación de productos a CSV para WooCommerce.
- Almacenamiento local de credenciales mediante keyring.
- Copias de seguridad de cambios pendientes.
- Icono personalizado de la aplicación.
- Generación del ejecutable para Windows.
- Script automatizado de compilación y distribución.
- Número de versión visible en la pantalla principal.

### Mejorado

- Diseño visual de la aplicación.
- Legibilidad de las tablas.
- Columnas fijas de selección y título.
- Gestión de estados de disponibilidad.
- Mensajes informativos, de error y de éxito.
- Validación y gestión de cambios pendientes de guardar.

### Corregido

- Incidencias relacionadas con la recomprobación de productos en SD.
- Problemas durante el guardado de fichas revisadas.
- Incidencias en la generación de archivos CSV.
- Advertencias de sintaxis en mensajes de la interfaz.

### Validación

- 143 pruebas automatizadas superadas.
- 190 subpruebas superadas.
- 14 pruebas omitidas.
- Comprobación inicial del ejecutable en Windows.

### Limitaciones conocidas

- El ejecutable todavía no dispone de firma digital.
- La sección de inventario actual está pendiente de desarrollo.
- La consulta automática de distribuidores está disponible actualmente para SD Distribuciones.
