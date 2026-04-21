"""Redact likely-secret values from strings before they hit the logs.

Used on HTTP response bodies from OAuth and platform API calls. Most
provider errors are harmless JSON, but their 4xx bodies can echo back
bits of the request (including refresh tokens and client secrets) and
Whoop's recovery endpoint can return biometric data. Always pipe
through redact_secrets() before logging.
"""

import re

_SECRET_FIELDS = (
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "bearer_token",
    "api_key",
    "password",
    "code",
    "token",
)

_FIELD_RE = re.compile(
    r'("(?:' + "|".join(_SECRET_FIELDS) + r')"\s*:\s*")[^"]*(")',
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\b(Bearer\s+)\S+", re.IGNORECASE)

_MAX_LEN = 500


def redact_secrets(text: str | None, max_len: int = _MAX_LEN) -> str:
    """Return a copy of `text` with common secret patterns masked and length capped."""
    if not text:
        return text or ""
    out = _FIELD_RE.sub(r"\1<redacted>\2", text)
    out = _BEARER_RE.sub(r"\1<redacted>", out)
    if len(out) > max_len:
        out = out[:max_len] + "... (truncated)"
    return out
