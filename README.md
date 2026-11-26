# Yumekai · Importador y gestor de catálogo

Aplicación interna de escritorio en Python y PySide6, con API PHP junto a WordPress/WooCommerce. La versión del programa se define en yumekai_importer/version.py. Las novedades pendientes de distribución se recogen en CHANGELOG.md.

| Pantalla | Función |
|---|---|
| Importar | Leer catálogos Excel y guardar fichas en la base del importador. |
| Revisar pendientes | Completar y revisar propuestas; preparar la exportación a WooCommerce. |
| Productos en tienda | Consultar WooCommerce, revisar SD, editar productos simples, crear borradores, publicar y despublicar. |

Revisar pendientes y Productos en tienda son pantallas separadas.

## Actualizar una instalación existente

La aplicación requiere los endpoints compatibles de api-importador y su configuración privada en el servidor. Mantener las credenciales fuera del repositorio.

El repositorio contiene las fuentes. El programa para distribuir se obtiene en Windows ejecutando:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\build.ps1
```

El resultado es `releases\Yumekai-v<VERSION>-Windows.zip`, que incluye `Yumekai\Yumekai.exe` y sus dependencias. Se comparte el ZIP completo; la aplicación usa una distribución en carpeta. El número de versión del ZIP se obtiene de APP_VERSION.

Para desarrollar desde una carpeta nueva:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m yumekai_importer
```

## Aspecto y acciones

Las pantallas comparten tipografía, espaciado, tablas, casillas grandes, avisos con cierre y botones:

| Aspecto | Uso |
|---|---|
| Amarillo | Acción principal del momento: guardar, crear o publicar. |
| Claro con borde | Acciones secundarias: editar y actualizar. |
| Lavanda | Consultar al distribuidor. |
| Rosa | Despublicar o borrar. |
| Discreto | Limpiar filtros y abrir la ficha web. |

La revisión de colección/tomo usa el mismo diálogo por campos que las propuestas SD: Aplicar, Producto, Campo, Actual y Propuesto. Se puede corregir Propuesto y guardar lo aceptado en una sola revisión. Los cuadros de confirmación comparten la jerarquía visual y los botones habituales se muestran en español.

En tienda se elimina el menú técnico Herramientas: queda Actualizar tienda. Recuperar revisión sin guardar solo aparece cuando hay una copia local. Los registros siguen en Ayuda y registros. En pendientes, Organizar fichas contiene duplicados y revisión de colección/tomo; Actualizar lista vuelve a leer ambas listas del importador. Comprobar productos ya subidos ejecuta el cruce manual con WooCommerce.

## Lectura y edición de la tienda

La lista se obtiene de WooCommerce, no de la copia de fichas del importador. Actualizar tienda inicia una consulta nueva. Volver desde Inicio conserva la última lectura para evitar consultas repetidas.

El filtro de publicación ofrece Publicados, Borradores y Todo el catálogo; este último incluye privados y pendientes, excluyendo papelera. La columna Publicación distingue su estado de publicación de la disponibilidad de existencias. Se conserva el listado anterior si falla una página, cambia el número de resultados o se cancela la lectura.

Se muestran contador y tiempo mientras se consulta. Cancelar lectura detiene las páginas pendientes y espera las peticiones en curso; cada petición tiene 5 s de conexión y 35 s sin respuesta. La sincronización ya realizada de la copia del importador no se deshace al cancelar su lectura posterior.

Ver ficha web abre el enlace exacto del ID seleccionado, incluso si está en borrador, para comprobar tomos y ediciones sin confundir productos por su título.

Doble clic abre el editor de un producto simple, o la revisión de propuestas SD si las tiene. Los campos sin editar se conservan. Si una edición manual falla, su copia local se recupera al abrir la ficha de nuevo; puedes revisarla frente a Datos recibidos o descartarla expresamente. El PVP y el precio rebajado son independientes. Las descripciones se editan como texto/HTML guardado; WordPress aplica su limpieza habitual al texto que se modifica. La pestaña Datos recibidos muestra la ficha y sus metadatos adicionales como consulta.

Las categorías se seleccionan por su ID real. El tipo Manga/Manhwa/Manhua se obtiene de las categorías y su jerarquía; se reconoce `Manwha`. Solo se usa `_yk_item_kind` como respaldo si no hay categoría reconocida. Leer no cambia la tienda. Modificar categorías en el editor alinea también ese metadato antiguo. Si hay tipos contradictorios en ramas distintas, se informa del problema.

### Crear, publicar y despublicar

Nuevo producto crea un producto simple como borrador. Requiere título, SKU único, impuesto y disponibilidad. Si se escribe ISBN/referencia se propone `YMK-código`, que puede editarse. El formulario permite preparar los datos bibliográficos, las categorías y las descripciones. Para publicar un borrador simple debe tener título y PVP.

Una creación sin confirmar se guarda localmente antes del envío. Recuperar creación reenvía la misma solicitud; el servidor conserva su identificador con el producto para devolver el mismo ID tras una respuesta perdida. No se reintentan escrituras automáticamente. Al confirmar la creación se consulta Borradores. Si se recupera un producto que ya cambió de estado, se consulta su estado actual.

Despublicar retira los productos marcados de la web pasando su estado a borrador. Conserva ID, SKU, metadatos y vínculo. Desde Borradores, Publicar vuelve a publicar los mismos productos. Ambas acciones muestran confirmación con ID, título e ISBN. La retirada se verifica en la base de datos antes y después de confirmar la transacción. Después se solicita a W3 Total Cache que invalide el producto y su URL; los avisos de caché se distinguen del guardado del estado. En un borrador, Comprobar retirada vuelve a verificarlo y solicita esa renovación sin publicarlo primero. Esta versión no hace borrado permanente.

Cada edición comprueba la versión leída. Si alguien cambió el producto en WooCommerce, se rechaza la edición y se pide recargar. Los resultados se confirman por producto: un conflicto no se presenta como un guardado correcto. Las operaciones se dividen en lotes de 20 y se detienen si hay resultados sin confirmar.

Alcance del editor: productos simples y los campos indicados. Portadas/galerías, variaciones, atributos, unidades de inventario, estados fiscales y demás campos específicos se consultan cuando están presentes, pero se mantienen y se gestionan desde WooCommerce en esta versión. La disponibilidad de un producto que gestiona unidades no se cambia desde este editor ni desde SD.

### Copia del importador y SD

El cruce con WooCommerce se inicia manualmente mediante Comprobar productos ya subidos, después de importar el CSV en la tienda. Actualizar lista vuelve a leer Por revisar y Listas para subir sin iniciar ese cruce.

Las fichas que ya existen en WooCommerce se vinculan por ISBN/referencia y salen de ambas listas; también se reconocen borradores, privados y pendientes de publicación. Su historial se conserva. Un cambio o borrado externo no devuelve automáticamente esas fichas a pendientes. Los productos creados directamente en WooCommerce se ven en Productos en tienda aunque no tengan ficha previa en el importador.

El flujo SD sigue utilizando `store_review.php` y sus validaciones originales. En tienda trabaja con productos publicados. Las propuestas se revisan por campo antes de aplicarse. Confirmar la revisión descarta los campos desmarcados; cancelar conserva las propuestas. La tabla mantiene siempre los valores guardados en la tienda hasta confirmar un cambio.

| Distribuidor | Editoriales admitidas |
|---|---|
| SD Distribuciones | Dolmen, RBA, Sekai, Pika, Kibook, Panini, Ivrea, Arechi |
| Norma Editorial | Norma |
| Milky Way | Milky Way |
| Planeta | Planeta |

Solo la consulta de SD está implementada; los otros distribuidores figuran como próximamente. Se bloquean consultas de editoriales incompatibles.

## Origen de los datos

Se usan las funciones de WooCommerce y sus setters para guardar, conservando sus hooks y cachés. Las tablas de esta instalación tienen prefijo `6PgMu3p_`; el código obtiene el prefijo de WordPress.

| Campo del programa | Dato de la tienda |
|---|---|
| ID, título, publicación y modificación | `posts.ID`, `post_title`, `post_status`, `post_modified_gmt` |
| Sinopsis / descripción larga | `posts.post_content` |
| Descripción corta | `posts.post_excerpt` |
| ISBN / referencia | `postmeta._yk_isbn`; si falta, `_global_unique_id` o el código de un SKU `YMK-…` |
| SKU | `postmeta._sku` |
| PVP / rebajado / precio activo | `_regular_price`, `_sale_price`, `_price` |
| Disponibilidad / unidades / gestión / reservas | `_stock_status`, `_stock`, `_manage_stock`, `_backorders` |
| Editorial / autoría / colección | `_yk_brand`, `_yk_author`, `_yk_franchise` |
| Tomo / formato / idioma / páginas | `_yk_volume`, `_yk_format`, `_yk_language`, `_yk_pages` |
| Tipo de obra / demografía | Términos `product_cat` y sus padres; `_yk_item_kind` es respaldo de tipo de obra |
| Categorías | `term_relationships` → `term_taxonomy` → `terms`, taxonomía `product_cat` |
| Tipo técnico del producto | Taxonomía WooCommerce `product_type`: simple, variable, etc. |
| Portada | `_thumbnail_id` → adjunto de WordPress |
| Impuesto | `_tax_class`, `_tax_status` |
| Destacado | Visibilidad de producto gestionada por WooCommerce |

Por ejemplo, Tower of God con términos 20 `Manwha/Manhua` y 30 `Manwha` se interpreta como Manhwa aunque `_yk_item_kind` conserve `manga`. No se confunde `product_type=simple` con el tipo de obra.

## Registros y pruebas

Ayuda y registros permite abrir la carpeta local y exportar un paquete de diagnóstico. El registro guarda eventos, errores y tiempos, sin incluir contraseñas ni cabeceras de autenticación. Los registros del servidor dependen de la configuración PHP y son independientes de los registros locales.

La carga registra `store.page_loaded` con tiempos de arranque de WordPress y consulta, `store.loaded` con tiempo de lectura/red y `store.rendered` con tiempo de tabla. La aplicación evita cachés persistentes en las peticiones de API y precarga también los adjuntos para evitar una consulta por portada. El tiempo real tras esta actualización debe comprobarse con el catálogo de Hostalia.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
php tests/test_store_catalog.php
php tests/test_store_sync.php
```

Las pruebas PHP requieren PDO y PDO SQLite y usan dobles de WordPress/WooCommerce; no consultan ni modifican la tienda. Las pruebas con servicios simulados no sustituyen la validación de la integración completa en Hostalia, WooCommerce y Windows. Verificar la instalación, los tiempos reales y el ejecutable antes de distribuir.

Si una revisión local pertenece a fichas que ya salieron de pendientes, se conserva aparte en `revisiones-fuera-de-pendientes.json` y no vuelve a introducir esos productos en las listas.

Referencias técnicas: [consultas de productos](https://developer.woocommerce.com/docs/features/products/wc-get-products/) y [modelo de producto simple](https://woocommerce.github.io/code-reference/classes/WC-Product-Simple.html).

Para caché se utilizan las constantes estándar de [WooCommerce](https://woocommerce.github.io/code-reference/files/woocommerce-includes-class-wc-cache-helper.html) y la API por producto/URL de [W3 Total Cache](https://github.com/BoldGrid/w3-total-cache/blob/master/w3-total-cache-api.php).

## Búsqueda, títulos e ISBN

- Búsqueda por título, ISBN, autoría, SKU y colección con espera de 200 ms tras la última pulsación. El filtrado reutiliza las filas cargadas y mantiene alineadas las columnas fijas.
- Revisión de colección/tomo por diferencias: numeración intermedia, etiquetas de edición conservadas, rangos de packs y propuesta de tomo 1 cuando no se identifica numeración, respetando los valores existentes según el flujo de revisión.
- Limpieza de sufijos finales COMIC, (COMIC) y (COMIC MANGA), en nuevas importaciones y desde la revisión de pendientes.
- Normalización de códigos numéricos sin espacios ni guiones, incluidos ISBN-10 y códigos largos admitidos. Los registros históricos no se renombran automáticamente.
- Consulta SD mediante códigos normalizados y equivalencias válidas ISBN-10/ISBN-13. La búsqueda por título verifica el código de la ficha principal antes de aceptarla.
- Equivalencias de temática acordadas y diferencias de clasificación y autoría propuestas para revisión. Los nombres múltiples se separan mediante /.
- Una consulta fallida o un producto no localizado no se interpreta como falta de existencias.
- Las cargas completas sin incidencias pendientes se limpian de la pantalla tras guardarlas; los casos pendientes requieren revisión.

## Eliminar recuperaciones locales

Ayuda y registros → Eliminar recuperaciones locales… permite seleccionar categorías o descartarlas todas, sin conexión al servidor.

| Recuperación | Archivo |
| --- | --- |
| Pendientes | review-recovery.json |
| Revisiones archivadas | revisiones-fuera-de-pendientes.json |
| Propuestas SD de tienda | store-recovery.json |
| Ediciones manuales sin confirmar | store-edit-recovery.json |
| Creación sin confirmar | store-creation.json |
| Temporales | Prefijos .review- y .create- |

La limpieza descarta también las propuestas correspondientes en memoria para que no reaparezcan al cerrar. Se bloquea durante operaciones en curso y comunica las eliminaciones incompletas.

Los productos del servidor se conservan. Si una creación llegó a completarse en WooCommerce, borrar su recuperación no elimina el producto: comprobar la tienda antes de volver a crearlo.

Los registros, credenciales y archivos exportados no forman parte de esta limpieza de recuperaciones.

## Registro local e inicio

El archivo yumekai.log conserva eventos y errores entre sesiones. Rota aproximadamente a los 2 MiB y mantiene cinco copias anteriores. Ayuda y registros permite abrir la carpeta o exportar un diagnóstico ZIP.

El inicio utiliza el logo vectorial assets/logo-yumekai.svg y mantiene los tres accesos independientes. La versión visible procede de yumekai_importer/version.py.
