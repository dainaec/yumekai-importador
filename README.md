# Yumekai · Importador y gestor de catálogo

Aplicación de escritorio para la importación, gestión, revisión y preparación del catálogo de productos de Yumekai para WooCommerce.

**Versión actual:** 0.1.0  
**Plataforma:** Windows  
**Estado:** En desarrollo  
**Uso:** Interno y privado

## Funcionalidades

- Importación de catálogos de distribuidores desde archivos Excel.
- Normalización y validación de fichas de productos.
- Detección de ISBN repetidos e incidencias de importación.
- Gestión de fichas pendientes de revisión.
- Edición de información comercial y bibliográfica.
- Búsqueda y filtrado de productos.
- Detección de títulos duplicados.
- Revisión de colecciones y números de tomo.
- Consulta de disponibilidad e información en SD Distribuciones.
- Clasificación de productos por tipo de obra y demografía.
- Cálculo del precio de venta rebajado.
- Gestión de estados de disponibilidad.
- Copias de seguridad locales de cambios pendientes de revisión.
- Preparación de productos para WooCommerce.
- Exportación de fichas mediante archivos CSV.
- Conexión con una API privada para la gestión centralizada del catálogo.

## Tecnologías

- Python
- PySide6
- openpyxl
- requests
- lxml
- keyring
- truststore
- PHP
- MySQL
- WooCommerce
- PyInstaller
- pytest

## Estructura del proyecto

| Directorio o archivo | Descripción |
|---|---|
| `yumekai_importer/assets/` | Recursos gráficos de la aplicación. |
| `yumekai_importer/catalog/` | Lógica de clasificación, validación y revisión. |
| `yumekai_importer/importers/` | Importadores y consultas a distribuidores. |
| `yumekai_importer/storage/` | Comunicación con la API, almacenamiento y exportaciones. |
| `yumekai_importer/ui/` | Ventanas, componentes, estilos y procesos de la interfaz. |
| `api-importador/` | Código PHP de la API privada. |
| `tests/` | Pruebas automatizadas. |
| `build.ps1` | Script de compilación para Windows. |
| `requirements.txt` | Dependencias de ejecución. |
| `requirements-dev.txt` | Dependencias de desarrollo y compilación. |
| `CHANGELOG.md` | Historial de versiones. |

## Instalación para desarrollo

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
python -m pip install -r requirements-dev.txt
```

## Ejecutar la aplicación

```powershell
python -m yumekai_importer
```

## Pruebas automatizadas

```powershell
python -m pytest -q
```

## Generar el ejecutable

```powershell
.\build.ps1
```

El proceso genera el ejecutable de Windows y un archivo ZIP con los componentes necesarios para distribuir la aplicación.

- `dist/Yumekai/Yumekai.exe`
- `releases/Yumekai-v0.1.0-Windows.zip`

## Instalación para usuarios

1. Descargar el archivo ZIP de la versión correspondiente.
2. Extraer su contenido en una carpeta local.
3. Ejecutar `Yumekai.exe`.
4. Configurar las credenciales de acceso a la API.

No es necesario instalar Python ni las dependencias del proyecto.

La carpeta `_internal` debe permanecer junto al ejecutable.

Las compilaciones sin firma digital pueden estar sujetas a bloqueos de seguridad de Windows.

## Seguridad y privacidad

Las credenciales de acceso a Hostalia se almacenan localmente mediante keyring y no deben incluirse en el código fuente ni en el repositorio.

El catálogo se gestiona de forma centralizada mediante una API privada.

Los archivos de datos locales, exportaciones y compilaciones se excluyen del control de versiones.

## Funcionalidades pendientes

- Gestión del inventario actual.
- Ampliación de las consultas a otros distribuidores.
- Mejoras en la automatización del catálogo.
- Integración directa con WooCommerce.
- Firma digital del ejecutable.

## Versionado

La aplicación utiliza versionado semántico: `MAJOR.MINOR.PATCH`.

La versión se define en `yumekai_importer/version.py`.

Los cambios de cada versión se documentan en `CHANGELOG.md`.

## Licencia

Software privado desarrollado para uso interno de Yumekai. No se autoriza su distribución pública sin permiso.