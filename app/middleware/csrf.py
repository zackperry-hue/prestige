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


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip CSRF for exempt paths
        if _is_exempt(request.url.path):
            return await call_next(request)

        # Skip safe methods — just ensure a token cookie exists
        if request.method not in UNSAFE_METHODS:
            response = await call_next(request)
            # Set cookie if not already present
            if CSRF_COOKIE_NAME not in request.cookies:
                token = _generate_csrf_token()
                response.set_cookie(
                    key=CSRF_COOKIE_NAME,
                    value=token,
                    httponly=False,  # JS needs to read it for HTMX
                    secure=settings.environment != "development",
                    samesite="lax",
                    max_age=60 * 60 * 24,  # 24 hours
                )
            return response

        # Validate CSRF for unsafe methods
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        if not cookie_token:
            logger.warning("CSRF: missing cookie on %s %s", request.method, request.url.path)
            return Response(status_code=403, content="CSRF validation failed")

        # Check header first (for HTMX/AJAX requests), then form field
        submitted_token = request.headers.get(CSRF_HEADER_NAME)

        if not submitted_token:
            # Need to peek at form data — cache it for the route handler
            content_type = request.headers.get("content-type", "")
            if "form" in content_type:
                # Read form and cache the body so downstream handlers can re-read it
                form = await request.form()
                submitted_token = form.get(CSRF_FIELD_NAME)

        if not submitted_token or not hmac.compare_digest(cookie_token, submitted_token):
            logger.warning("CSRF: token mismatch on %s %s", request.method, request.url.path)
            return Response(status_code=403, content="CSRF validation failed")

        response = await call_next(request)

        # Rotate token after successful unsafe request
        new_token = _generate_csrf_token()
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=new_token,
            httponly=False,
            secure=settings.environment != "development",
            samesite="lax",
            max_age=60 * 60 * 24,
        )

        return response
