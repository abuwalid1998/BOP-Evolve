"""Prototype authentication helpers.

Mock login is for the local demo only. Production must use the bank-approved
SSO / OIDC identity provider with MFA, and must not rely on local passwords.
"""

import hashlib
import hmac
import secrets
from datetime import datetime

import jwt

from app.config import get_settings

_ITERATIONS = 240_000
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS).hex()
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    return hmac.compare_digest(candidate, digest)


def issue_token(user_id: str, session_id: str, expires_at: datetime) -> str:
    payload = {"sub": user_id, "sid": session_id, "exp": int(expires_at.timestamp())}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=[_ALGORITHM])
