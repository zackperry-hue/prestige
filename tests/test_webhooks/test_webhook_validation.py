"""Tests for webhook signature validation."""

import hashlib
import hmac
import time
from unittest.mock import patch

from app.services.webhook_validator import validate_strava_verify_token, validate_whoop_signature


class TestWhoopSignatureValidation:
    def test_valid_signature(self):
        secret = "test-whoop-secret"
        body = b'{"type": "workout.updated", "id": "abc-123"}'
        timestamp = str(int(time.time()))  # Use current time to pass freshness check

        message = f"{timestamp}.".encode() + body
        signature = hmac.HMAC(secret.encode(), message, hashlib.sha256).hexdigest()

        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.whoop_webhook_secret = secret
            assert validate_whoop_signature(body, timestamp, signature) is True

    def test_invalid_signature(self):
        timestamp = str(int(time.time()))
        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.whoop_webhook_secret = "real-secret"
            assert validate_whoop_signature(b"body", timestamp, "bad-sig") is False

    def test_empty_secret_rejects(self):
        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.whoop_webhook_secret = ""
            assert validate_whoop_signature(b"anything", "12345", "anything") is False

    def test_stale_timestamp_rejects(self):
        """Timestamps older than 5 minutes should be rejected to prevent replay attacks."""
        secret = "test-whoop-secret"
        body = b'{"type": "workout.updated"}'
        stale_timestamp = str(int(time.time()) - 600)  # 10 minutes ago

        message = f"{stale_timestamp}.".encode() + body
        signature = hmac.HMAC(secret.encode(), message, hashlib.sha256).hexdigest()

        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.whoop_webhook_secret = secret
            assert validate_whoop_signature(body, stale_timestamp, signature) is False


class TestStravaVerifyToken:
    def test_valid_token(self):
        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.strava_verify_token = "my-verify-token"
            assert validate_strava_verify_token("my-verify-token") is True

    def test_invalid_token(self):
        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.strava_verify_token = "my-verify-token"
            assert validate_strava_verify_token("wrong-token") is False

    def test_empty_secret_rejects(self):
        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.strava_verify_token = ""
            assert validate_strava_verify_token("anything") is False
