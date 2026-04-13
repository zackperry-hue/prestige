"""Webhook signature validation for Whoop and Strava."""

import hashlib
import hmac
import logging
import time

from app.config import settings

logger = logging.getLogger(__name__)

# Maximum age of a webhook timestamp before it's rejected (5 minutes)
_MAX_WEBHOOK_AGE_SECONDS = 300


def validate_whoop_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Validate Whoop webhook HMAC-SHA256 signature.

    Whoop computes: HMAC-SHA256(secret, timestamp + "." + body)
    Also validates timestamp freshness to prevent replay attacks.
    """
    if not settings.whoop_webhook_secret:
        logger.error("WHOOP_WEBHOOK_SECRET not set, rejecting webhook")
        return False

    # Check timestamp freshness to prevent replay attacks
    try:
        ts = int(timestamp)
        now = int(time.time())
        if abs(now - ts) > _MAX_WEBHOOK_AGE_SECONDS:
            logger.warning("Whoop webhook timestamp too old: %s (age: %ds)", timestamp, abs(now - ts))
            return False
    except (ValueError, OverflowError):
        logger.warning("Invalid Whoop webhook timestamp: %s", timestamp)
        return False

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
        logger.error("STRAVA_VERIFY_TOKEN not set, rejecting verification")
        return False
    return verify_token == settings.strava_verify_token


def validate_strava_webhook_payload(body: bytes) -> bool:
    """Validate a Strava webhook POST payload.

    Strava doesn't send per-event HMAC signatures, but we validate that
    the payload contains the expected structure to reject garbage/forged requests.
    Returns True if the payload looks like a legitimate Strava event.
    """
    import json

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("Strava webhook: invalid JSON body")
        return False

    # Strava events must have object_type, aspect_type, object_id, owner_id
    required_fields = {"object_type", "aspect_type", "object_id", "owner_id"}
    if not required_fields.issubset(payload.keys()):
        logger.warning("Strava webhook: missing required fields: %s", required_fields - payload.keys())
        return False

    # object_type must be one of Strava's known types
    if payload["object_type"] not in ("activity", "athlete"):
        logger.warning("Strava webhook: unknown object_type: %s", payload["object_type"])
        return False

    # aspect_type must be one of Strava's known types
    if payload["aspect_type"] not in ("create", "update", "delete"):
        logger.warning("Strava webhook: unknown aspect_type: %s", payload["aspect_type"])
        return False

    return True
