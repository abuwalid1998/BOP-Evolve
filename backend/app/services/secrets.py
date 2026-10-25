"""Encryption of configuration secrets (stored database passwords).

Production must supply CONFIG_SECRET_KEY from the bank's secrets manager. In
development the key is derived from JWT_SECRET so the prototype works out of
the box. Decrypted values are only ever used server-side to open connections.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.config_secret_key.strip()
    if not key:
        digest = hashlib.sha256(b"bop-evolve-config-v1:" + settings.jwt_secret.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode())


def key_is_configured() -> bool:
    return bool(get_settings().config_secret_key.strip())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored password cannot be decrypted with the current key") from exc
