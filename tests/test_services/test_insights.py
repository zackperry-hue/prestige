"""Tests for workout insights generation."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.workout import NormalizedWorkout
from app.services.workout_insights import (
    _format_duration_delta,
    _format_pace,
    _pct_change,
)


class TestHelpers:
    def test_pct_change_increase(self):
        assert _pct_change(110, 100) == pytest.approx(10.0)

    def test_pct_change_decrease(self):
        assert _pct_change(90, 100) == pytest.approx(-10.0)

    def test_pct_change_zero_base(self):
        assert _pct_change(100, 0) == 0.0

    def test_format_duration_delta_seconds(self):
        assert _format_duration_delta(45) == "45s"

    def test_format_duration_delta_minutes(self):
        assert _format_duration_delta(185) == "3m 5s"

    def test_format_duration_delta_hours(self):
        assert _format_duration_delta(3665) == "1h 1m"

    def test_format_pace_normal(self):
        # 5km in 25 minutes = 5.0 min/km
        assert _format_pace(5000.0, 1500) == pytest.approx(5.0)

    def test_format_pace_no_distance(self):
        assert _format_pace(None, 1500) is None
        assert _format_pace(0, 1500) is None

    def test_format_pace_no_time(self):
        assert _format_pace(5000.0, 0) is None
