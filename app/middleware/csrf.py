"""CSRF protection middleware using double-submit cookie pattern.

Generates a random CSRF token stored in a cookie and injects it into
template context. POST/PATCH/DELETE requests must include the token
as a form field or header, matching the cookie value.

Exempt paths (webhooks, API endpoints) are skipped.
"""

import hashlib
import hmac
import logging
import secrets
from urllib.parse import parse_qs

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import settings

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "csrf_token"
CSRF_FIELD_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_TOKEN_LENGTH = 32

# Paths that don't require CSRF validation (webhooks, health checks, etc.)
EXEMPT_PREFIXES = (
    "/webhooks/",
    "/health",
    "/api/",
)

# Methods that require CSRF validation
UNSAFE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


def _generate_csrf_token() -> str:
    """Generate a random CSRF token."""
    return secrets.token_hex(CSRF_TOKEN_LENGTH)


def _sign_token(token: str) -> str:
    """Sign a CSRF token with the app secret to prevent forgery."""
    return hmac.new(
        settings.app_secret_key.encode(),
        token.encode(),
        hashlib.sha256,
    ).hexdigest()


def _is_exempt(path: str) -> bool:
    """Check if a path is exempt from CSRF protection."""
    return any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def _set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,  # JS needs to read it for HTMX
        secure=settings.environment != "development",
        samesite="lax",
        max_age=60 * 60 * 24,  # 24 hours
    )


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip CSRF for exempt paths
        if _is_exempt(request.url.path):
            return await call_next(request)

        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)

        # Safe methods: make sure a token is available to templates, generating
        # one up-front if the cookie is missing so the template and the
        # response cookie agree on the same value.
        if request.method not in UNSAFE_METHODS:
            needs_cookie = not cookie_token
            if needs_cookie:
                cookie_token = _generate_csrf_token()
            request.state.csrf_token = cookie_token
            response = await call_next(request)
            if needs_cookie:
                _set_csrf_cookie(response, cookie_token)
            return response

        # Unsafe methods: validate
        if not cookie_token:
            logger.warning("CSRF: missing cookie on %s %s", request.method, request.url.path)
            return Response(status_code=403, content="CSRF validation failed")

        # Check header first (for HTMX/AJAX requests), then form field.
        # When we read the form body here we must also buffer + replay it so
        # the downstream FastAPI handler can still parse email/password etc.
        # Otherwise BaseHTTPMiddleware leaves the body stream exhausted.
        submitted_token = request.headers.get(CSRF_HEADER_NAME)
        if not submitted_token:
            content_type = request.headers.get("content-type", "")
            if "application/x-www-form-urlencoded" in content_type:
                body_bytes = await request.body()
                try:
                    parsed = parse_qs(body_bytes.decode("utf-8", errors="replace"))
                    values = parsed.get(CSRF_FIELD_NAME, [])
                    submitted_token = values[0] if values else None
                except Exception:
                    submitted_token = None

                replayed = False

                async def _replay_receive() -> dict:
                    nonlocal replayed
                    if replayed:
                        return {"type": "http.disconnect"}
                    replayed = True
                    return {"type": "http.request", "body": body_bytes, "more_body": False}

                request._receive = _replay_receive

        if not submitted_token or not hmac.compare_digest(cookie_token, submitted_token):
            logger.warning("CSRF: token mismatch on %s %s", request.method, request.url.path)
            return Response(status_code=403, content="CSRF validation failed")

        # Rotate BEFORE the handler runs so any re-rendered form (e.g. the
        # error page on a failed login) embeds the new token that will match
        # the cookie we set on the response.
        new_token = _generate_csrf_token()
        request.state.csrf_token = new_token

        response = await call_next(request)
        _set_csrf_cookie(response, new_token)
        return response
