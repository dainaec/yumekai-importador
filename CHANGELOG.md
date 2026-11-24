# Historial de cambios

Todos los cambios relevantes del importador y gestor de catálogo de Yumekai se documentarán en este archivo.

El proyecto utiliza versionado semántico.

## [Sin publicar]

### Añadido

### Mejorado

### Corregido

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