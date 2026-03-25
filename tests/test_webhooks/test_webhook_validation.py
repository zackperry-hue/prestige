"""Tests for webhook signature validation."""

import hashlib
import hmac
from unittest.mock import patch

from app.services.webhook_validator import validate_strava_verify_token, validate_whoop_signature


class TestWhoopSignatureValidation:
    def test_valid_signature(self):
        secret = "test-whoop-secret"
        body = b'{"type": "workout.updated", "id": "abc-123"}'
        timestamp = "1711382400"

        message = f"{timestamp}.".encode() + body
        signature = hmac.HMAC(secret.encode(), message, hashlib.sha256).hexdigest()

        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.whoop_webhook_secret = secret
            assert validate_whoop_signature(body, timestamp, signature) is True

    def test_invalid_signature(self):
        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.whoop_webhook_secret = "real-secret"
            assert validate_whoop_signature(b"body", "12345", "bad-sig") is False

    def test_empty_secret_skips_validation(self):
        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.whoop_webhook_secret = ""
            assert validate_whoop_signature(b"anything", "12345", "anything") is True


class TestStravaVerifyToken:
    def test_valid_token(self):
        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.strava_verify_token = "my-verify-token"
            assert validate_strava_verify_token("my-verify-token") is True

    def test_invalid_token(self):
        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.strava_verify_token = "my-verify-token"
            assert validate_strava_verify_token("wrong-token") is False

    def test_empty_secret_skips_validation(self):
        with patch("app.services.webhook_validator.settings") as mock_settings:
            mock_settings.strava_verify_token = ""
            assert validate_strava_verify_token("anything") is True
