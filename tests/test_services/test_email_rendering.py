"""Tests for email template rendering."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.schemas.workout import NormalizedWorkout
from app.services.email_service import (
    _format_distance,
    _format_duration,
    _format_elevation,
    _format_pace,
    _sport_type_display,
)
from app.services.workout_insights import Insight, WorkoutHighlights

# Load the legacy single-workout template directly for render tests.
# The production flow now uses render_session_email, but these tests validate
# the legacy template is still intact for backward-compat.
_template_dir = Path(__file__).parent.parent.parent / "app" / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_template_dir)), autoescape=True)


def render_workout_email(user, workout, highlights):
    """Test helper: render the legacy single-workout email template."""
    template = _jinja_env.get_template("workout_summary.html")
    return template.render(
        display_name=user.display_name or user.email.split("@")[0],
        platform=workout.platform,
        sport_type_display=_sport_type_display(workout.sport_type),
        workout_date_full=workout.started_at.strftime("%m/%d/%Y"),
        workout_date_short=workout.started_at.strftime("%a %b %d"),
        workout_time=workout.started_at.strftime("%I:%M %p"),
        duration_display=_format_duration(workout.duration_seconds),
        distance_display=_format_distance(workout.distance_meters),
        pace_display=_format_pace(workout.distance_meters, workout.duration_seconds),
        calories=workout.calories,
        avg_heart_rate=workout.avg_heart_rate,
        max_heart_rate=workout.max_heart_rate,
        strain_score=workout.strain_score,
        elevation_gain=_format_elevation(workout.elevation_gain),
        avg_power_watts=workout.avg_power_watts,
        insights=highlights.insights,
        workouts_this_week=highlights.total_workouts_this_week,
        workouts_this_month=highlights.total_workouts_this_month,
        streak_days=highlights.streak_days,
    )


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
    def test_miles_default(self):
        # Default unit_system is imperial
        assert _format_distance(5012.3) == "3.11 mi"

    def test_kilometers(self):
        assert _format_distance(5012.3, "metric") == "5.01 km"

    def test_meters(self):
        assert _format_distance(800.0, "metric") == "800 m"

    def test_none(self):
        assert _format_distance(None) is None

    def test_zero(self):
        assert _format_distance(0) is None


class TestFormatPace:
    def test_normal_pace_imperial(self):
        # 5km in 25 min ≈ 8:03 /mi
        result = _format_pace(5000.0, 1500)
        assert result is not None
        assert "/mi" in result

    def test_normal_pace_metric(self):
        # 5km in 25 min = 5:00 /km
        assert _format_pace(5000.0, 1500, "metric") == "5:00 /km"

    def test_fast_pace_metric(self):
        # 10km in 35 min = 3:30 /km
        assert _format_pace(10000.0, 2100, "metric") == "3:30 /km"

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
        assert "3.11 mi" in html
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
