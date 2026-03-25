"""Webhook signature validation for Whoop and Strava."""

import hashlib
import hmac
import logging

from app.config import settings

logger = logging.getLogger(__name__)


def validate_whoop_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Validate Whoop webhook HMAC-SHA256 signature.

    Whoop computes: HMAC-SHA256(secret, timestamp + "." + body)
    """
    if not settings.whoop_webhook_secret:
        logger.warning("WHOOP_WEBHOOK_SECRET not set, skipping validation")
        return True

    message = f"{timestamp}.".encode() + body
    expected = hmac.HMAC(
        settings.whoop_webhook_secret.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def validate_strava_verify_token(verify_token: str) -> bool:
    """Validate Strava subscription verification token."""
    if not settings.strava_verify_token:
        logger.warning("STRAVA_VERIFY_TOKEN not set, skipping validation")
        return True
    return verify_token == settings.strava_verify_token
