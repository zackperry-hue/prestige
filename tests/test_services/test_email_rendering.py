"""Tests for email template rendering."""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.schemas.workout import NormalizedWorkout
from app.services.email_service import (
    _format_distance,
    _format_duration,
    _format_pace,
    render_workout_email,
)
from app.services.workout_insights import Insight, WorkoutHighlights


@dataclass
class FakeUser:
    display_name: str | None = "Alex"
    email: str = "alex@test.com"


class TestFormatDuration:
    def test_seconds_only(self):
        assert _format_duration(45) == "0:45"

    def test_minutes_and_seconds(self):
        assert _format_duration(185) == "3:05"

    def test_hours(self):
        assert _format_duration(3661) == "1:01:01"

    def test_zero(self):
        assert _format_duration(0) == "0:00"


class TestFormatDistance:
    def test_kilometers(self):
        assert _format_distance(5012.3) == "5.01 km"

    def test_meters(self):
        assert _format_distance(800.0) == "800 m"

    def test_none(self):
        assert _format_distance(None) is None

    def test_zero(self):
        assert _format_distance(0) is None


class TestFormatPace:
    def test_normal_pace(self):
        # 5km in 25 min = 5:00/km
        assert _format_pace(5000.0, 1500) == "5:00"

    def test_fast_pace(self):
        # 10km in 35 min = 3:30/km
        assert _format_pace(10000.0, 2100) == "3:30"

    def test_no_distance(self):
        assert _format_pace(None, 1500) is None
        assert _format_pace(0, 1500) is None


class TestRenderWorkoutEmail:
    def _make_user(self, **kwargs):
        return FakeUser(**kwargs)

    def _make_workout(self, **kwargs):
        defaults = {
            "platform": "strava",
            "platform_workout_id": "12345",
            "sport_type": "running",
            "started_at": datetime(2026, 3, 25, 8, 30, 0, tzinfo=UTC),
            "ended_at": datetime(2026, 3, 25, 9, 0, 0, tzinfo=UTC),
            "duration_seconds": 1800,
            "distance_meters": 5000.0,
            "calories": 400.0,
            "avg_heart_rate": 155.0,
            "max_heart_rate": 178.0,
            "strain_score": None,
            "elevation_gain": 45.0,
            "avg_power_watts": None,
            "raw_data": {},
        }
        defaults.update(kwargs)
        return NormalizedWorkout(**defaults)

    def _make_highlights(self, **kwargs):
        defaults = {
            "insights": [],
            "total_workouts_this_week": 3,
            "total_workouts_this_month": 12,
            "streak_days": 2,
        }
        defaults.update(kwargs)
        return WorkoutHighlights(**defaults)

    def test_renders_basic_email(self):
        html = render_workout_email(
            self._make_user(),
            self._make_workout(),
            self._make_highlights(),
        )

        assert "Workout Summary for" in html
        assert "03/25/2026" in html
        assert "Running" in html
        assert "strava" in html.lower()
        assert "5.00 km" in html
        assert "400" in html  # calories
        assert "155" in html  # avg HR
        assert "this week" in html
        assert "this month" in html

    def test_renders_whoop_strain(self):
        html = render_workout_email(
            self._make_user(),
            self._make_workout(platform="whoop", strain_score=14.2),
            self._make_highlights(),
        )

        assert "14.2" in html
        assert "Strain" in html

    def test_renders_insights(self):
        highlights = self._make_highlights(
            insights=[
                Insight(label="Pace", message="0.15 min/km faster than last time", direction="up"),
                Insight(label="Heart Rate", message="Avg HR 5 bpm lower — better efficiency", direction="up"),
            ],
        )
        html = render_workout_email(
            self._make_user(),
            self._make_workout(),
            highlights,
        )

        assert "Highlights" in html
        assert "faster than last time" in html
        assert "better efficiency" in html

    def test_renders_streak(self):
        html = render_workout_email(
            self._make_user(),
            self._make_workout(),
            self._make_highlights(streak_days=5),
        )

        assert "5-day" in html
        assert "streak" in html

    def test_renders_weekly_monthly_counts(self):
        html = render_workout_email(
            self._make_user(),
            self._make_workout(),
            self._make_highlights(total_workouts_this_week=4, total_workouts_this_month=15),
        )

        assert "4" in html
        assert "this week" in html
        assert "15" in html
        assert "this month" in html

    def test_no_display_name_still_renders(self):
        html = render_workout_email(
            self._make_user(display_name=None, email="runner42@gmail.com"),
            self._make_workout(),
            self._make_highlights(),
        )

        assert "Workout Summary for" in html
        assert "03/25/2026" in html

    def test_cycling_shows_power(self):
        html = render_workout_email(
            self._make_user(),
            self._make_workout(sport_type="cycling", avg_power_watts=210.0),
            self._make_highlights(),
        )

        assert "210" in html
        assert "Avg Power" in html
