from cryptography.fernet import Fernet

from app.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if not settings.token_encryption_key:
            raise ValueError("TOKEN_ENCRYPTION_KEY must be set")
        _fernet = Fernet(settings.token_encryption_key.encode())
    return _fernet


def encrypt_token(token: str) -> bytes:
    return _get_fernet().encrypt(token.encode())


def decrypt_token(encrypted: bytes) -> str:
    return _get_fernet().decrypt(encrypted).decode()
