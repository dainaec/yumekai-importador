import keyring


SERVICE_NAME = "Yumekai Importador - Hostalia"


def load_credentials() -> tuple[str, str] | None:
    credential = keyring.get_credential(SERVICE_NAME, None)
    if credential is None:
        return None
    return credential.username, credential.password


def save_credentials(username: str, password: str) -> None:
    keyring.set_password(SERVICE_NAME, username, password)