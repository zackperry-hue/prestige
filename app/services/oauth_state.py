"""OAuth state parameter generation and validation.

Prevents CSRF attacks by signing the state with a server-side secret.
The state encodes the user_id and a random nonce, signed with HMAC-SHA256.
Format: base64(user_id:nonce:signature)
"""

import hashlib
import hmac
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode

from app.config import settings


def generate_oauth_state(user_id: str) -> str:
    """Generate a signed OAuth state parameter containing the user_id."""
    nonce = secrets.token_hex(16)
    payload = f"{user_id}:{nonce}"
    signature = hmac.new(
        settings.app_secret_key.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    state = f"{payload}:{signature}"
    return urlsafe_b64encode(state.encode()).decode()


def validate_oauth_state(state: str) -> str | None:
    """Validate a signed OAuth state and return the user_id, or None if invalid."""
    try:
        decoded = urlsafe_b64decode(state.encode()).decode()
        parts = decoded.split(":")
        if len(parts) != 3:
            return None
        user_id, nonce, signature = parts
        payload = f"{user_id}:{nonce}"
        expected = hmac.new(
            settings.app_secret_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        return user_id
    except Exception:
        return None
