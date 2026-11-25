# Yumekai · Importador y gestor de catálogo

Aplicación de escritorio para importar catálogos de distribuidores, revisar fichas y preparar productos para WooCommerce. Permite consultar SD Distribuciones y gestionar propuestas de actualización de productos ya publicados desde el programa.

**Última versión de distribución interna:** 0.1.0  
**Versión declarada en el código:** 0.1.0  
**Plataforma de distribución:** Windows  
**Estado:** En desarrollo  
**Uso:** Interno y privado

Las novedades posteriores a la primera distribución se recogen en [Sin publicar](CHANGELOG.md#sin-publicar). La conexión de actualización con la tienda está implementada y probada localmente; su comprobación en Hostalia sigue pendiente.

## Flujo de trabajo

| Sección | Uso |
|---|---|
| **Importar catálogo** | Cargar Excel, consultar incidencias y guardar las fichas pendientes en la base del importador. |
| **Revisar → Preparar fichas** | Consultar SD, editar y completar fichas, revisar propuestas y gestionar las listas Por revisar y Listas para subir. |
| **Revisar → En tienda** | Leer los productos publicados de WooCommerce, consultar SD y aplicar únicamente los cambios aceptados. |

El acceso **Productos en tienda** del inicio abre la pestaña En tienda dentro del mismo espacio de revisión. La consulta a distribuidores se centraliza en Revisar.

## Funcionalidades

### Importación y revisión

- Lectura de catálogos Excel de SD Distribuciones y Norma Editorial.
- Conservación de filas originales e incidencias, con exportación a Excel para revisarlas y volver a cargarlas.
- Detección de ISBN/códigos repetidos y títulos duplicados, aunque tengan distinto identificador.
- Revisión de la colección y el número de tomo inferidos a partir del título.
- Edición de datos bibliográficos y comerciales mediante doble clic en la ficha.
- Tablas con todos los campos, desplazamiento horizontal y columnas fijas de selección y título.
- Búsqueda por título, ISBN/código, autoría o colección; filtros combinables y acceso a fichas con datos pendientes.
- Acciones sobre varias fichas, con confirmación para el borrado.
- Mensajes diferenciados de información, éxito y error.
- Tema claro propio para mantener la legibilidad con Windows en modo oscuro.

### Excepciones y campos obligatorios

Los códigos no estándar se conservan completos como texto, incluidos códigos más largos de 13 caracteres y ceros iniciales. El límite de almacenamiento previsto es de 128 caracteres, sin saltos de línea ni caracteres de control.

| Operación | Campos obligatorios | Datos que pueden autorizarse con avisos |
|---|---|---|
| Guardar una importación | ISBN/código y título. | Código fuera del estándar ISBN-13 y PVP pendiente o no positivo. |
| Pasar a Listas para subir | ISBN/código, título y estado Yumekai. | Código no estándar, PVP pendiente y demás datos incompletos. |

La autorización tiene dos pasos: marcar expresamente las fichas con excepciones y confirmar un segundo resumen antes del envío. Las casillas empiezan sin marcar y el permiso corresponde a ese envío, no a un desbloqueo permanente.

Las fichas no autorizadas permanecen pendientes. Un PVP ausente se guarda vacío y se exporta vacío; no se sustituye por cero. Los códigos largos deben guardarse como texto en Excel para evitar que el propio archivo altere sus dígitos.

### Recomprobación en SD

El menú **Recomprobar → SD Distribuciones** permite consultar las fichas seleccionadas en dos modos:

- **Ficha completa:** propone completar datos pendientes, normalizar el formato y preparar la sinopsis.
- **Solo disponibilidad:** propone exclusivamente cambios de estado.

Los resultados quedan como propuestas locales hasta que se revisan y guardan. La comparación muestra el valor actual y el propuesto y permite aceptar campos individuales. Los campos desmarcados siguen pendientes.

La búsqueda admite códigos no estándar y comprueba la coincidencia con el producto solicitado. Un error, una consulta detenida o un producto no encontrado no se interpreta como falta de stock.

### Reglas de disponibilidad

| Resultado de SD | Estado Yumekai |
|---|---|
| En stock / Stock: Sí | Bajo demanda (`yk_on_demand`). |
| Sin stock / Stock: No | Sin existencias (`outofstock`). |
| Consultar disponibilidad y publicación posterior al día de consulta | Se puede reservar (`onbackorder`). |
| Consultar disponibilidad y publicación de hoy o anterior | Sin existencias (`outofstock`). |
| Consulta fallida, producto no encontrado o fecha necesaria sin confirmar | Se conserva el estado anterior y se informa del motivo. |

Se utiliza la fecha de publicación, no la de última actualización. La referencia temporal es el día de la consulta en la zona de la tienda. Cuando SD confirma un estado, se aplica la regla del distribuidor aunque el estado anterior fuera Hay existencias (`instock`).

### Clasificación y formato

Se gestionan los tipos de obra Manga, Manhwa y Manhua y las demografías/categorías propias de Yumekai, con las siguientes equivalencias de SD:

| Valor de SD | Valor de Yumekai |
|---|---|
| Teen's Love, Yaoi, Boys Love | Yaoi / BL. |
| Spokon | Shonen. |
| Manga adulto, Terror | Seinen. |
| Novelas manga, Artbooks | Artbooks, guías y novelas. |
| Yuri | Yuri. |

Las variantes de Cartoné, con o sin tilde, se convierten en **Tapa dura**. Los formatos vacíos o que contienen una demografía o tipo de obra se convierten en **Rústica**. Los demás formatos se conservan según SD, con la normalización de la etiqueta simple Rústica.

### Sinopsis

La revisión completa de SD prepara el formateo de la sinopsis actual: une saltos simples dentro de un párrafo y conserva los espacios en blanco que separan párrafos. El cambio se muestra antes de guardarlo.

Si falta el texto, puede completarse desde SD. Si el texto guardado parece recortado y SD amplía el mismo comienzo, se propone recuperarlo. Un texto diferente no reemplaza automáticamente una sinopsis ya existente.

Los contenidos con HTML, listas reconocibles, diálogos con guion o palabras partidas se conservan y muestran un aviso para revisión manual.

### Productos publicados en WooCommerce

La pestaña **En tienda** lee los valores actuales de los productos publicados. La referencia de edición es la ficha de WooCommerce, no la copia anterior del importador.

1. Filtrar y marcar los productos que se quieren consultar.
2. Elegir ficha completa o solo disponibilidad en Recomprobar SD.
3. Pulsar **Revisar y aplicar en tienda**.
4. Comparar los valores y desmarcar los campos que no se acepten. Doble clic abre los valores completos para compararlos.
5. Pulsar **Aplicar cambios seleccionados** para enviarlos.

Si hay fichas marcadas, se revisan las propuestas de esas fichas; si no hay ninguna marcada, se revisan todas las propuestas pendientes.

La conexión permite actualizar estado, sinopsis, autoría, editorial, colección, tomo, idioma, formato, páginas, tipo de obra y PVP pendiente. Si falta el precio rebajado al proponer un PVP, se propone también el descuento del 5 % como campo independiente.

La identificación se hace por ID de WordPress, incluso cuando se repite un ISBN. El título, identificador, SKU, categorías, portada, CSS y demás campos no aceptados no se reescriben. Esta conexión no crea ni elimina productos publicados.

Antes de guardar, la API compara la versión actual con la leída inicialmente. La comprobación incluye el contenido y los metadatos leídos y detecta diferencias dentro del mismo segundo. Una ficha con conflicto queda pendiente y las demás pueden continuar.

Las actualizaciones se envían en lotes de 20 con un resultado por producto. Ante una desconexión o un resultado sin confirmar se detienen los envíos siguientes y se conservan las propuestas para comprobar el resultado antes de reintentar.

### Exportación CSV

- Exportación de las fichas seleccionadas o visibles de Listas para subir.
- Comprobación previa de datos pendientes, con las opciones de devolver las fichas a revisión o generar el CSV igualmente.
- Contrato de 63 columnas adaptado al importador nativo de WooCommerce y a los metadatos de Yumekai.
- SKU `YMK-<ISBN/código>`, precio normal PVP y precio rebajado calculado con un descuento del 5 % y aritmética decimal.
- Categorías según tipo de obra y demografía. Shōjo se exporta como **Shojo**, manteniendo la etiqueta de la aplicación.
- Clase de impuesto `tasa-reducida` por defecto y los cuatro estados Yumekai.
- Referencia opcional a un CSV exportado de WordPress para recuperar ID y el nombre real del CSS asociado, sin inventar identificadores ni archivos CSS.

Los valores de Publicado son `1` para publicado, `-1` para borrador y `0` para privado. Generar un CSV no confirma que se haya importado en WooCommerce ni mueve automáticamente las fichas fuera de Listas para subir.

Los CSV pueden contener sinopsis con varias líneas dentro de una celda. Cualquier división o procesamiento del archivo debe respetar su estructura CSV.

## Tecnologías

| Ámbito | Tecnologías |
|---|---|
| Escritorio | Python, PySide6. |
| Excel y datos | openpyxl, Decimal. |
| HTTP y consultas SD | requests, lxml, truststore. |
| Credenciales | keyring y gestor de credenciales del sistema. |
| API y catálogo centralizado | PHP, PDO, MySQL. |
| Tienda | WordPress y WooCommerce. |
| Distribución | PyInstaller y PowerShell. |
| Pruebas | unittest; ejecución compatible con pytest. |

## Estructura del proyecto

| Directorio o archivo | Descripción |
|---|---|
| `yumekai_importer/assets/` | Icono y recursos gráficos. |
| `yumekai_importer/catalog/` | Clasificación, validaciones, reglas SD, sinopsis y propuestas de cambios. |
| `yumekai_importer/importers/` | Lectura de Excel y consultas a distribuidores. |
| `yumekai_importer/storage/` | Cliente de la API, credenciales, recuperación y exportación CSV. |
| `yumekai_importer/ui/` | Ventanas, componentes, estilos y procesos en segundo plano. |
| `api-importador/` | API PHP propia; se despliega como `importer-api` en el servidor. |
| `tests/` | Pruebas de lógica, interfaz, API y regresiones. |
| `yumekai_importer/version.py` | Nombre y versión de la aplicación. |
| `Yumekai.spec` | Configuración de PyInstaller. |
| `build.ps1` | Compilación y empaquetado para Windows. |
| `requirements.txt` | Dependencias de ejecución. |
| `requirements-dev.txt` | Dependencias de desarrollo y compilación. |
| `CHANGELOG.md` | Historial de versiones y cambios sin publicar. |

## Instalación para desarrollo

El proyecto se desarrolla y distribuye para Windows. El entorno original utiliza Python 3.13.

Clonar el repositorio privado:

```powershell
git clone https://github.com/dainaec/yumekai-importador.git
cd yumekai-importador
```

Crear y activar el entorno virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Instalar las dependencias:

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

### Acceso a la API

El programa utiliza el usuario y la contraseña de la API privada de Hostalia. Son credenciales de la API, no las del FTP o la base de datos.

Se guardan mediante `keyring`, con el nombre de servicio `Yumekai Importador - Hostalia`. En un entorno de desarrollo pueden configurarse sin escribir la contraseña en el código ni en el historial de comandos:

```powershell
python -c "from getpass import getpass; from yumekai_importer.storage.credentials import save_credentials; save_credentials(input('Usuario de la API: '), getpass('Contraseña de la API: '))"
```

La configuración es local a cada equipo. El ejecutable y el repositorio no incluyen las credenciales. La aplicación utiliza el acceso previamente guardado; actualmente no incorpora un asistente de configuración dentro de la interfaz.

### Ejecutar la aplicación

```powershell
python -m yumekai_importer
```

## API propia y despliegue

La API existente necesita PHP con PDO y acceso a la base MySQL del importador. Su carpeta `importer-api` debe mantener la protección Basic Auth configurada en el servidor y utilizar HTTPS.

Los scripts del catálogo cargan la conexión PDO desde `importer-private/database.php`, fuera de la raíz pública. La conexión de tienda carga el `wp-load.php` de WordPress situado en la carpeta superior a `importer-api`.

| Endpoint o archivo | Función |
|---|---|
| `health.php` | Comprobar el acceso a la base del importador. |
| `create_product.php` | Guardar importaciones y comprobar la autorización de excepciones. |
| `products.php`, `review_products.php` | Consultar, editar y gestionar fichas pendientes y listas para subir. |
| `sync_store.php` | Vincular fichas del importador con los ID de WooCommerce. |
| `inventory_products.php` | Consultar las fichas del importador que ya están vinculadas a la tienda. |
| `store_review.php` | Leer productos publicados y aplicar cambios aceptados mediante WooCommerce. |
| `store_common.php` | Lectura de fichas, versiones y validación de campos de tienda. |
| `review_common.php`, `exception_rules.php` | Validaciones y reglas compartidas de la API. |

Para desplegar la conexión de actualización, subir **`store_common.php` y `store_review.php` a la API propia**, junto al resto de sus archivos. Las operaciones se realizan desde el programa y no requieren editar el plugin de la tienda.

En instalaciones antiguas, comprobar que la tabla `products` de la base del importador admite los códigos ampliados: `isbn VARCHAR(128)` y `sku VARCHAR(160)`. El script `ampliar_codigos_productos.sql` se entregó con la actualización de excepciones y corresponde exclusivamente a esa base. La actualización de conexión de tienda no requiere otra migración SQL.

Tras cambiar el código Python hay que volver a compilar el ejecutable para distribuir esas funciones. Una compilación anterior no incorpora los cambios del código fuente.

## Recuperación y guardados pendientes

El programa conserva copias de recuperación en la ubicación local de datos de la aplicación:

- `review-recovery.json`: revisión de fichas pendientes y listas para subir.
- `store-recovery.json`: propuestas sobre productos publicados.

Se recuperan desde Herramientas en su sección correspondiente. La recuperación conserva los datos y la versión originales para detectar ediciones posteriores; no adapta las propuestas silenciosamente al estado nuevo del servidor.

Estas copias permiten recuperar trabajo pendiente; no sustituyen una copia de seguridad de las bases de datos. Solo se retiran como confirmados los cambios cuyo guardado se ha podido verificar.

## Pruebas automatizadas

Ejecutar desde la raíz del repositorio con el entorno virtual activo:

```powershell
python -m unittest discover -s tests -v
```

También pueden ejecutarse con pytest si está instalado en el entorno:

```powershell
python -m pytest -q
```

Las pruebas de interfaz pueden ejecutarse sin mostrar ventanas:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest discover -s tests -v
```

Las pruebas de API requieren un ejecutable PHP con PDO y SQLite para crear sus bases temporales. Puede localizarse mediante `PATH` o con la variable `YUMEKAI_TEST_PHP`. Sin un ejecutable PHP disponible se omiten esas pruebas; la aplicación de escritorio no necesita PHP instalado en el ordenador del usuario.

La última validación local del estado Sin publicar, realizada el 25/11/2026, completó **214 pruebas**. Incluye una API PHP real con un sustituto local de WordPress/WooCommerce; no equivale a una prueba de conexión o escritura en Hostalia ni reproduce todos los plugins o los bloqueos de MySQL de producción.

## Generar el ejecutable

```powershell
.\build.ps1
```

El script de distribución genera el ejecutable y un ZIP para Windows. Para la versión 0.1.0, las rutas de distribución son:

- `dist/Yumekai/Yumekai.exe`
- `releases/Yumekai-v0.1.0-Windows.zip`

La versión se define en `yumekai_importer/version.py`. La existencia de cambios en Sin publicar no implica que se haya generado o distribuido una nueva versión del ejecutable.

## Instalación para usuarios

1. Descargar el ZIP de la versión interna correspondiente.
2. Extraer todo su contenido en una carpeta local.
3. Disponer de las credenciales de la API configuradas en el gestor local de credenciales del equipo.
4. Ejecutar `Yumekai.exe`.

No es necesario instalar Python ni las dependencias de desarrollo. La carpeta `_internal` debe permanecer junto al ejecutable. Las compilaciones todavía no tienen firma digital y Windows puede mostrar una advertencia al abrirlas.

## Seguridad y privacidad

- Credenciales almacenadas localmente mediante keyring; no se incluyen en el código, los ZIP de distribución ni el repositorio.
- API privada sobre HTTPS, con protección Basic Auth en el servidor.
- Datos actuales de WooCommerce como referencia para revisar productos publicados.
- Escritura limitada a los campos aceptados y comprobación de versiones antes del guardado.
- Detención de envíos ante resultados sin confirmar y conservación de propuestas pendientes.
- Archivos de conexión privados y credenciales de base de datos fuera de la carpeta pública de la API.

Los catálogos de trabajo, exportaciones, copias locales de recuperación y compilaciones deben permanecer excluidos del control de versiones.

## Límites actuales y trabajo pendiente

- La conexión de actualización de tienda requiere la primera comprobación en Hostalia.
- Las actualizaciones directas están preparadas para productos simples. Los demás tipos quedan para revisión en WooCommerce.
- Si un producto gestiona unidades, no se desactiva esa gestión para forzar un estado del distribuidor; se informa de la incidencia.
- La conexión de productos publicados no descarga portadas ni modifica categorías o demografías, títulos, SKU o CSS.
- La lectura y actualización de tienda se limita a productos publicados; no crea ni elimina productos.
- La consulta automática de disponibilidad está implementada para SD. Norma tiene importación Excel; las consultas propias de Norma, Milky Way y DIRAC / Kibook siguen pendientes.
- La actualización se inicia manualmente desde el programa; no hay una sincronización periódica desatendida.
- Los textos con formato especial se conservan para revisión manual.
- El ejecutable no dispone de firma digital.

## Versionado

La aplicación utiliza versionado semántico `MAJOR.MINOR.PATCH`. La versión se define en `yumekai_importer/version.py` y los cambios se registran en [CHANGELOG.md](CHANGELOG.md).

Los cambios en desarrollo permanecen en Sin publicar hasta preparar y validar su distribución. El historial de una versión ya distribuida conserva sus resultados de validación originales.

## Licencia

Software privado desarrollado para uso interno de Yumekai. No se autoriza su distribución pública sin permiso.
