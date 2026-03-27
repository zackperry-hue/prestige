"""Email sending via SendGrid with Jinja2 template rendering."""

import logging
import uuid
from datetime import datetime
from pathlib import Path

import pytz
from jinja2 import Environment, FileSystemLoader
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.email_log import EmailLog
from app.models.user import User
from app.models.user_profile import UserProfile
from app.models.workout import Workout
from app.models.workout_session import WorkoutSession
from app.schemas.workout import NormalizedWorkout
from app.services.workout_insights import WorkoutHighlights

logger = logging.getLogger(__name__)

_template_dir = Path(__file__).parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_template_dir)), autoescape=True)

_METERS_PER_MILE = 1609.344
_METERS_PER_FOOT = 0.3048


def _format_duration(seconds: int) -> str:
    """Format seconds into H:MM:SS or M:SS."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_distance(meters: float | None, unit_system: str = "imperial") -> str | None:
    """Format meters into a human-readable string (miles or km)."""
    if meters is None or meters <= 0:
        return None
    if unit_system == "imperial":
        miles = meters / _METERS_PER_MILE
        return f"{miles:.2f} mi"
    if meters >= 1000:
        return f"{meters / 1000:.2f} km"
    return f"{int(meters)} m"


def _format_elevation(meters: float | None, unit_system: str = "imperial") -> str | None:
    """Format elevation gain in feet or meters."""
    if meters is None or meters <= 0:
        return None
    if unit_system == "imperial":
        feet = meters / _METERS_PER_FOOT
        return f"{int(feet)} ft"
    return f"{int(meters)} m"


def _format_pace(meters: float | None, seconds: int, unit_system: str = "imperial") -> str | None:
    """Format pace as M:SS /mi or /km."""
    if not meters or meters <= 0 or seconds <= 0:
        return None
    if unit_system == "imperial":
        miles = meters / _METERS_PER_MILE
        pace_seconds = int(seconds / miles)
        mins, secs = divmod(pace_seconds, 60)
        return f"{mins}:{secs:02d} /mi"
    km = meters / 1000
    pace_seconds = int(seconds / km)
    mins, secs = divmod(pace_seconds, 60)
    return f"{mins}:{secs:02d} /km"


def _sport_type_display(sport_type: str | None) -> str:
    """Convert normalized sport type to display name."""
    if not sport_type:
        return "Workout"
    return sport_type.replace("_", " ").title()


def _platform_color(platform: str) -> str:
    """Return brand color for a platform."""
    colors = {
        "strava": "#fc4c02",
        "whoop": "#00b388",
        "wahoo": "#0068b5",
    }
    return colors.get(platform, "#666666")


def _localize_time(dt: datetime, timezone_str: str) -> datetime:
    """Convert a UTC datetime to the user's local timezone."""
    try:
        user_tz = pytz.timezone(timezone_str)
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(user_tz)
    except Exception:
        return dt


def render_session_email(
    user: User,
    session: WorkoutSession,
    workouts: list[Workout],
    highlights: WorkoutHighlights,
    narrative: str | None = None,
) -> str:
    """Render the unified workout session email HTML."""
    template = _jinja_env.get_template("workout_session.html")
    units = getattr(user, "unit_system", "imperial")
    user_tz = getattr(user, "timezone", "UTC") or "UTC"

    # Convert to user's timezone
    local_start = _localize_time(session.started_at, user_tz)

    platforms = [p for p in session.platforms.split(",") if p]
    platform_colors = {p: _platform_color(p) for p in platforms}

    return template.render(
        display_name=user.display_name or user.email.split("@")[0],
        narrative=narrative,
        platforms=platforms,
        platform_colors=platform_colors,
        platform_count=len(platforms),
        sport_type_display=_sport_type_display(session.sport_type),
        workout_date_full=local_start.strftime("%m/%d/%Y"),
        workout_date_short=local_start.strftime("%a %b %d"),
        workout_time=local_start.strftime("%I:%M %p"),
        timezone_abbr=local_start.strftime("%Z"),
        # Merged best-of data
        duration_display=_format_duration(session.duration_seconds) if session.duration_seconds else None,
        distance_display=_format_distance(session.distance_meters, units),
        pace_display=_format_pace(session.distance_meters, session.duration_seconds or 0, units),
        calories=session.calories,
        avg_heart_rate=session.avg_heart_rate,
        max_heart_rate=session.max_heart_rate,
        strain_score=session.strain_score,
        recovery_score=session.recovery_score,
        hrv_rmssd=session.hrv_rmssd,
        elevation_gain=_format_elevation(session.elevation_gain, units),
        avg_power_watts=session.avg_power_watts,
        # Activity counts
        workouts_this_week=highlights.total_workouts_this_week,
        workouts_this_month=highlights.total_workouts_this_month,
        streak_days=highlights.streak_days,
    )


async def send_session_email(
    db: AsyncSession,
    user: User,
    session: WorkoutSession,
    workouts: list[Workout],
    highlights: WorkoutHighlights,
) -> bool:
    """Render and send a unified session summary email. Returns True on success."""
    if not user.email_enabled:
        logger.info("Email disabled for user %s, skipping", user.id)
        return False

    if not settings.sendgrid_api_key:
        logger.warning("SENDGRID_API_KEY not set, skipping email send")
        return False

    # Generate AI narrative
    from app.services.narrative_generator import generate_workout_narrative

    units = getattr(user, "unit_system", "imperial")
    user_name = user.display_name or user.email.split("@")[0]

    # Load user profile for personalized insights
    from sqlalchemy import select
    profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    profile = profile_result.scalar_one_or_none()

    narrative = await generate_workout_narrative(session, highlights, user_name, units, profile=profile)

    html_content = render_session_email(user, session, workouts, highlights, narrative=narrative)

    user_tz = getattr(user, "timezone", "UTC") or "UTC"
    local_start = _localize_time(session.started_at, user_tz)
    sport_display = _sport_type_display(session.sport_type)
    date_str = local_start.strftime("%m/%d/%Y")
    subject = f"Workout Summary — {sport_display} on {date_str}"

    message = Mail(
        from_email=settings.sendgrid_from_email,
        to_emails=user.email,
        subject=subject,
        html_content=html_content,
    )

    log_entry = EmailLog(user_id=user.id)

    try:
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(message)
        log_entry.sendgrid_msg_id = response.headers.get("X-Message-Id", "")
        log_entry.status = "sent"
        logger.info("Sent session email to %s (status %s)", user.email, response.status_code)
    except Exception as e:
        log_entry.status = "failed"
        log_entry.error_message = str(e)
        logger.exception("Failed to send session email to %s", user.email)

    db.add(log_entry)
    await db.commit()
    return log_entry.status == "sent"


# Keep legacy function for backward compatibility
async def send_workout_email(
    db: AsyncSession,
    user: User,
    workout: NormalizedWorkout,
    workout_id: uuid.UUID,
    highlights: WorkoutHighlights,
) -> bool:
    """Legacy single-workout email. Delegates to session email when possible."""
    # This is kept for any direct calls but the main flow now uses send_session_email
    if not user.email_enabled:
        return False
    if not settings.sendgrid_api_key:
        return False

    units = getattr(user, "unit_system", "imperial")
    template = _jinja_env.get_template("workout_summary.html")

    html_content = template.render(
        display_name=user.display_name or user.email.split("@")[0],
        platform=workout.platform,
        sport_type_display=_sport_type_display(workout.sport_type),
        workout_date_full=workout.started_at.strftime("%m/%d/%Y"),
        workout_date_short=workout.started_at.strftime("%a %b %d"),
        workout_time=workout.started_at.strftime("%I:%M %p"),
        duration_display=_format_duration(workout.duration_seconds),
        distance_display=_format_distance(workout.distance_meters, units),
        pace_display=_format_pace(workout.distance_meters, workout.duration_seconds, units),
        calories=workout.calories,
        avg_heart_rate=workout.avg_heart_rate,
        max_heart_rate=workout.max_heart_rate,
        strain_score=workout.strain_score,
        elevation_gain=_format_elevation(workout.elevation_gain, units),
        avg_power_watts=workout.avg_power_watts,
        insights=highlights.insights,
        workouts_this_week=highlights.total_workouts_this_week,
        workouts_this_month=highlights.total_workouts_this_month,
        streak_days=highlights.streak_days,
    )

    sport_display = _sport_type_display(workout.sport_type)
    date_str = workout.started_at.strftime("%m/%d/%Y")
    subject = f"Workout Summary for {date_str} — {sport_display} via {workout.platform.title()}"

    message = Mail(
        from_email=settings.sendgrid_from_email,
        to_emails=user.email,
        subject=subject,
        html_content=html_content,
    )

    log_entry = EmailLog(user_id=user.id, workout_id=workout_id)

    try:
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(message)
        log_entry.sendgrid_msg_id = response.headers.get("X-Message-Id", "")
        log_entry.status = "sent"
    except Exception as e:
        log_entry.status = "failed"
        log_entry.error_message = str(e)
        logger.exception("Failed to send workout email to %s", user.email)

    db.add(log_entry)
    await db.commit()
    return log_entry.status == "sent"
