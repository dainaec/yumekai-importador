"""Delete local recovery copies without contacting the server."""
from pathlib import Path


RECOVERY_GROUPS = {
    "pending": (
        "Revisión de pendientes",
        ("review-recovery.json",),
    ),
    "archived": (
        "Revisiones archivadas fuera de pendientes",
        ("revisiones-fuera-de-pendientes.json",),
    ),
    "store": (
        "Propuestas SD de tienda",
        ("store-recovery.json",),
    ),
    "manual": (
        "Ediciones de tienda pendientes",
        ("store-edit-recovery.json",),
    ),
    "creation": (
        "Creación de producto pendiente",
        ("store-creation.json",),
    ),
    "temporary": (
        "Temporales de recuperación",
        (),
    ),
}


def recovery_directory() -> Path:
    from PySide6.QtCore import QStandardPaths

    value = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if not value:
        raise OSError("No se pudo localizar la carpeta de datos de Yumekai.")

    return Path(value)


def delete_local_recoveries(groups, *, directory=None):
    selected = set(groups)

    if selected - RECOVERY_GROUPS.keys():
        raise ValueError("La selección contiene una recuperación desconocida.")

    if not selected:
        return set(), 0, {}

    folder = recovery_directory() if directory is None else Path(directory)

    if not folder.is_absolute():
        raise ValueError("La carpeta de recuperaciones debe ser absoluta.")

    cleared, deleted, failures = set(), 0, {}

    for group, (_, names) in RECOVERY_GROUPS.items():
        if group not in selected:
            continue

        try:
            if group == "temporary":
                try:
                    paths = [
                        path
                        for path in folder.iterdir()
                        if path.name.startswith((".review-", ".create-"))
                    ]
                except FileNotFoundError:
                    paths = []
            else:
                paths = [folder / name for name in names]
        except OSError as error:
            failures[group] = str(error)
            continue

        errors = []

        for path in paths:
            try:
                path.unlink()
                deleted += 1
            except FileNotFoundError:
                pass
            except OSError as error:
                errors.append(f"{path.name}: {error}")

        if errors:
            failures[group] = "\n".join(errors)
        else:
            cleared.add(group)

    return cleared, deleted, failures