"""Email sending via SendGrid with Jinja2 template rendering."""

import logging
import uuid
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.email_log import EmailLog
from app.models.user import User
from app.schemas.workout import NormalizedWorkout
from app.services.workout_insights import WorkoutHighlights

logger = logging.getLogger(__name__)

_template_dir = Path(__file__).parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_template_dir)), autoescape=True)


def _format_duration(seconds: int) -> str:
    """Format seconds into H:MM:SS or M:SS."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_distance(meters: float | None) -> str | None:
    """Format meters into a human-readable string."""
    if meters is None or meters <= 0:
        return None
    if meters >= 1000:
        return f"{meters / 1000:.2f} km"
    return f"{int(meters)} m"


def _format_pace(meters: float | None, seconds: int) -> str | None:
    """Format pace as M:SS /km."""
    if not meters or meters <= 0 or seconds <= 0:
        return None
    km = meters / 1000
    pace_seconds = int(seconds / km)
    mins, secs = divmod(pace_seconds, 60)
    return f"{mins}:{secs:02d}"


def _sport_type_display(sport_type: str) -> str:
    """Convert normalized sport type to display name."""
    return sport_type.replace("_", " ").title()


def render_workout_email(
    user: User,
    workout: NormalizedWorkout,
    highlights: WorkoutHighlights,
) -> str:
    """Render the workout summary email HTML."""
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
        elevation_gain=workout.elevation_gain,
        avg_power_watts=workout.avg_power_watts,
        # Highlights
        insights=highlights.insights,
        workouts_this_week=highlights.total_workouts_this_week,
        workouts_this_month=highlights.total_workouts_this_month,
        streak_days=highlights.streak_days,
    )


async def send_workout_email(
    db: AsyncSession,
    user: User,
    workout: NormalizedWorkout,
    workout_id: uuid.UUID,
    highlights: WorkoutHighlights,
) -> bool:
    """Render and send a workout summary email. Returns True on success."""
    if not user.email_enabled:
        logger.info("Email disabled for user %s, skipping", user.id)
        return False

    if not settings.sendgrid_api_key:
        logger.warning("SENDGRID_API_KEY not set, skipping email send")
        return False

    html_content = render_workout_email(user, workout, highlights)
    sport_display = _sport_type_display(workout.sport_type)
    date_str = workout.started_at.strftime("%m/%d/%Y")
    subject = f"Workout Summary for {date_str} — {sport_display} via {workout.platform.title()}"

    message = Mail(
        from_email=settings.sendgrid_from_email,
        to_emails=user.email,
        subject=subject,
        html_content=html_content,
    )

    log_entry = EmailLog(
        user_id=user.id,
        workout_id=workout_id,
    )

    try:
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(message)
        log_entry.sendgrid_msg_id = response.headers.get("X-Message-Id", "")
        log_entry.status = "sent"
        logger.info("Sent workout email to %s (status %s)", user.email, response.status_code)
    except Exception as e:
        log_entry.status = "failed"
        log_entry.error_message = str(e)
        logger.exception("Failed to send workout email to %s", user.email)

    db.add(log_entry)
    await db.commit()
    return log_entry.status == "sent"
