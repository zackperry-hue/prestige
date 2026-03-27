"""Session manager: match, merge, and schedule emails for cross-platform workout sessions.

When a workout arrives from any platform:
1. Look for an existing session with overlapping time (±15 min)
2. If found, merge the new workout data into that session
3. If not, create a new session and schedule email for 10 min later
4. A background job checks for sessions ready to email
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import PlatformConnection
from app.models.workout import Workout
from app.models.workout_session import WorkoutSession
from app.schemas.workout import NormalizedWorkout

logger = logging.getLogger(__name__)

# How close two workouts need to be to count as the same session
MATCH_WINDOW_MINUTES = 15

# How long to wait after the first workout before sending the email
EMAIL_DELAY_MINUTES = 10


async def find_matching_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    workout: NormalizedWorkout,
) -> WorkoutSession | None:
    """Find an existing session that overlaps with this workout's time window."""
    window = timedelta(minutes=MATCH_WINDOW_MINUTES)
    workout_start = workout.started_at
    workout_end = workout.ended_at or (workout_start + timedelta(seconds=workout.duration_seconds or 0))

    result = await db.execute(
        select(WorkoutSession).where(
            WorkoutSession.user_id == user_id,
            # Overlapping time window: session start within window of workout, or vice versa
            or_(
                and_(
                    WorkoutSession.started_at >= workout_start - window,
                    WorkoutSession.started_at <= workout_end + window,
                ),
                and_(
                    WorkoutSession.ended_at >= workout_start - window,
                    WorkoutSession.ended_at <= workout_end + window,
                ),
            ),
        ).order_by(WorkoutSession.started_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


def _merge_field(current, new, prefer_new: bool = False):
    """Merge a field: prefer non-None, optionally prefer new value."""
    if new is None:
        return current
    if current is None:
        return new
    return new if prefer_new else current


def merge_into_session(session: WorkoutSession, workout: NormalizedWorkout, platform: str):
    """Merge workout data into an existing session, taking the best value from each platform."""

    # Expand time window to cover both
    if workout.started_at < session.started_at:
        session.started_at = workout.started_at
    workout_end = workout.ended_at or (workout.started_at + timedelta(seconds=workout.duration_seconds or 0))
    if session.ended_at is None or workout_end > session.ended_at:
        session.ended_at = workout_end

    # Duration: take the longer one (more complete recording)
    if workout.duration_seconds:
        if session.duration_seconds is None or workout.duration_seconds > session.duration_seconds:
            session.duration_seconds = workout.duration_seconds

    # Distance: prefer Strava (GPS-based, most accurate)
    if platform == "strava" and workout.distance_meters:
        session.distance_meters = workout.distance_meters
    elif session.distance_meters is None:
        session.distance_meters = workout.distance_meters

    # Calories: take the higher value (more sensors = more accurate)
    if workout.calories:
        if session.calories is None or workout.calories > session.calories:
            session.calories = workout.calories

    # Heart rate: prefer Whoop (chest-strap grade sensor)
    if platform == "whoop" and workout.avg_heart_rate:
        session.avg_heart_rate = workout.avg_heart_rate
        session.max_heart_rate = _merge_field(session.max_heart_rate, workout.max_heart_rate, prefer_new=True)
    elif session.avg_heart_rate is None:
        session.avg_heart_rate = workout.avg_heart_rate
        session.max_heart_rate = _merge_field(session.max_heart_rate, workout.max_heart_rate)

    # Elevation: prefer Strava (barometric altimeter + GPS)
    if platform == "strava" and workout.elevation_gain:
        session.elevation_gain = workout.elevation_gain
    elif session.elevation_gain is None:
        session.elevation_gain = workout.elevation_gain

    # Power: take whatever has it (usually Wahoo or Strava via power meter)
    session.avg_power_watts = _merge_field(session.avg_power_watts, workout.avg_power_watts)

    # Whoop-specific fields
    if platform == "whoop":
        session.strain_score = _merge_field(session.strain_score, workout.strain_score, prefer_new=True)

    # Sport type: prefer Strava's classification (most granular)
    if platform == "strava" and workout.sport_type:
        session.sport_type = workout.sport_type
    elif session.sport_type is None:
        session.sport_type = workout.sport_type

    # Track which platforms contributed
    existing_platforms = set(session.platforms.split(",")) if session.platforms else set()
    existing_platforms.discard("")
    existing_platforms.add(platform)
    session.platforms = ",".join(sorted(existing_platforms))


async def create_or_update_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    workout: NormalizedWorkout,
    workout_id: uuid.UUID,
) -> WorkoutSession:
    """Match workout to an existing session or create a new one. Returns the session."""

    existing_session = await find_matching_session(db, user_id, workout)

    if existing_session:
        logger.info(
            "Merging %s workout into existing session %s",
            workout.platform,
            existing_session.id,
        )
        merge_into_session(existing_session, workout, workout.platform)

        # Link the workout to this session
        await db.execute(
            update(Workout).where(Workout.id == workout_id).values(session_id=existing_session.id)
        )
        await db.commit()
        return existing_session

    # No match — create a new session
    workout_end = workout.ended_at or (
        workout.started_at + timedelta(seconds=workout.duration_seconds or 0)
    )

    # Only schedule email if workout happened AFTER the platform was connected
    # (historical backfill data should be stored but not emailed)
    email_scheduled_at = None
    conn_result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user_id,
            PlatformConnection.platform == workout.platform,
        )
    )
    connection = conn_result.scalar_one_or_none()
    if connection and workout.started_at >= connection.created_at:
        email_scheduled_at = datetime.now(UTC) + timedelta(minutes=EMAIL_DELAY_MINUTES)
    else:
        logger.info(
            "Skipping email for historical %s workout from %s (before connection)",
            workout.platform,
            workout.started_at,
        )

    session = WorkoutSession(
        user_id=user_id,
        sport_type=workout.sport_type,
        started_at=workout.started_at,
        ended_at=workout_end,
        duration_seconds=workout.duration_seconds,
        distance_meters=workout.distance_meters,
        calories=workout.calories,
        avg_heart_rate=workout.avg_heart_rate,
        max_heart_rate=workout.max_heart_rate,
        elevation_gain=workout.elevation_gain,
        avg_power_watts=workout.avg_power_watts,
        strain_score=workout.strain_score if workout.platform == "whoop" else None,
        platforms=workout.platform,
        email_scheduled_at=email_scheduled_at,
    )
    db.add(session)
    await db.flush()  # get the session ID

    # Link the workout to this session
    await db.execute(
        update(Workout).where(Workout.id == workout_id).values(session_id=session.id)
    )
    await db.commit()
    await db.refresh(session)

    logger.info(
        "Created new session %s from %s workout, email scheduled at %s",
        session.id,
        workout.platform,
        session.email_scheduled_at,
    )
    return session


async def get_sessions_ready_to_email(db: AsyncSession) -> list[WorkoutSession]:
    """Find sessions where the email delay has passed and email hasn't been sent."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(WorkoutSession).where(
            WorkoutSession.email_scheduled_at <= now,
            WorkoutSession.email_sent_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def get_session_workouts(db: AsyncSession, session_id: uuid.UUID) -> list[Workout]:
    """Get all workouts linked to a session."""
    result = await db.execute(
        select(Workout)
        .where(Workout.session_id == session_id)
        .order_by(Workout.platform)
    )
    return list(result.scalars().all())
