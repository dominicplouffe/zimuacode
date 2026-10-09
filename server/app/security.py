import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(("fernet:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt=salt)


def sign(data: Any, salt: str) -> str:
    return _serializer(salt).dumps(data)


def unsign(token: str, salt: str, max_age: int) -> Any | None:
    try:
        return _serializer(salt).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
