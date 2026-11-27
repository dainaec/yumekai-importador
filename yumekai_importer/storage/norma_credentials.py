"""Optional Norma access stored separately in the operating system keyring."""
import json

import keyring

from yumekai_importer.importers.norma.zonalibros import NormaCredentials


SERVICE_NAME = "Yumekai Importador - Norma ZonaLibros"
ACCOUNT_NAME = "norma"


def load_norma_credentials():
    payload = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
    if not payload:
        return None
    try:
        values = json.loads(payload)
        if isinstance(values, dict) and all(isinstance(values.get(key), str) and values[key]
                                            for key in ("tax_id", "username", "password")):
            return NormaCredentials(values["tax_id"], values["username"], values["password"])
    except (TypeError, ValueError):
        pass
    return None


def save_norma_credentials(credentials):
    # Called only after a successful login and an explicit choice to remember it.
    payload = json.dumps({"tax_id": credentials.tax_id, "username": credentials.username,
                          "password": credentials.password}, ensure_ascii=False)
    keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, payload)


def forget_norma_credentials():
    if keyring.get_password(SERVICE_NAME, ACCOUNT_NAME) is not None:
        keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
