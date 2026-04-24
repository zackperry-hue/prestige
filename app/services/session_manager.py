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

    stmt = (
        select(WorkoutSession)
        .where(
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
        )
        .order_by(WorkoutSession.started_at.desc())
        .limit(1)
        .with_for_update()
    )
    result = await db.execute(stmt)
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

    # Start time: prefer Strava/Wahoo (user-initiated) over Whoop (auto-detected)
    # Whoop often auto-detects workouts and may report an earlier start
    if platform in ("strava", "wahoo", "garmin"):
        session.started_at = workout.started_at
    elif workout.started_at < session.started_at and session.platforms in ("whoop", ""):
        # Only use Whoop start if no other platform has set it yet
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
        session.recovery_score = _merge_field(session.recovery_score, workout.recovery_score, prefer_new=True)
        session.hrv_rmssd = _merge_field(session.hrv_rmssd, workout.hrv_rmssd, prefer_new=True)
        session.sleep_hours = _merge_field(session.sleep_hours, workout.sleep_hours, prefer_new=True)
        session.sleep_performance = _merge_field(
            session.sleep_performance, workout.sleep_performance, prefer_new=True
        )

    # Activity context: Strava is authoritative (the athlete sets workout_type/name/description on Strava)
    if platform == "strava":
        session.workout_subtype = _merge_field(session.workout_subtype, workout.workout_subtype, prefer_new=True)
        session.activity_name = _merge_field(session.activity_name, workout.activity_name, prefer_new=True)
        session.activity_description = _merge_field(
            session.activity_description, workout.activity_description, prefer_new=True
        )
        session.athlete_count = _merge_field(session.athlete_count, workout.athlete_count, prefer_new=True)

    # HR zones: Whoop chest-strap data is the gold standard; Strava is fallback
    if platform == "whoop" and workout.hr_zone_durations:
        session.hr_zone_durations = workout.hr_zone_durations
    elif session.hr_zone_durations is None and workout.hr_zone_durations:
        session.hr_zone_durations = workout.hr_zone_durations

    # Power zones: Strava is the only current source
    if workout.power_zone_durations and session.power_zone_durations is None:
        session.power_zone_durations = workout.power_zone_durations

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

        # Schedule email if not already scheduled (e.g. first workout was historical)
        if existing_session.email_scheduled_at is None and existing_session.email_sent_at is None:
            conn_result = await db.execute(
                select(PlatformConnection).where(
                    PlatformConnection.user_id == user_id,
                    PlatformConnection.platform == workout.platform,
                )
            )
            connection = conn_result.scalar_one_or_none()
            if connection and workout.started_at >= connection.created_at:
                existing_session.email_scheduled_at = datetime.now(UTC) + timedelta(minutes=EMAIL_DELAY_MINUTES)
                logger.info("Scheduled email for merged session %s", existing_session.id)

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

    is_whoop = workout.platform == "whoop"
    is_strava = workout.platform == "strava"
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
        strain_score=workout.strain_score if is_whoop else None,
        recovery_score=workout.recovery_score if is_whoop else None,
        hrv_rmssd=workout.hrv_rmssd if is_whoop else None,
        sleep_hours=workout.sleep_hours if is_whoop else None,
        sleep_performance=workout.sleep_performance if is_whoop else None,
        workout_subtype=workout.workout_subtype if is_strava else None,
        activity_name=workout.activity_name if is_strava else None,
        activity_description=workout.activity_description if is_strava else None,
        athlete_count=workout.athlete_count if is_strava else None,
        hr_zone_durations=workout.hr_zone_durations,
        power_zone_durations=workout.power_zone_durations,
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


MAX_EMAIL_ATTEMPTS = 3


async def get_sessions_ready_to_email(db: AsyncSession) -> list[WorkoutSession]:
    """Find sessions where the email delay has passed and email hasn't been sent."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(WorkoutSession).where(
            WorkoutSession.email_scheduled_at <= now,
            WorkoutSession.email_sent_at.is_(None),
            WorkoutSession.email_attempts < MAX_EMAIL_ATTEMPTS,
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


async def enrich_session_with_daily_whoop(db: AsyncSession, session: WorkoutSession) -> None:
    """Pull daily Whoop recovery + sleep for the session date and attach them.

    Runs just before insight generation so a Strava-only (or Wahoo-only) ride
    can still benefit from Whoop's daily context. Only fills fields that are
    currently None — never overwrites values already supplied by a Whoop-recorded
    workout. Best-effort: any failure is logged and swallowed so the email still
    sends.
    """
    needs_recovery = session.recovery_score is None or session.hrv_rmssd is None
    needs_sleep = session.sleep_hours is None or session.sleep_performance is None
    if not needs_recovery and not needs_sleep:
        return

    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == session.user_id,
            PlatformConnection.platform == "whoop",
            PlatformConnection.is_active.is_(True),
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return

    try:
        from app.platforms.whoop_client import (
            extract_sleep_metrics,
            fetch_whoop_recovery,
            fetch_whoop_sleep,
            get_whoop_token,
        )

        token = await get_whoop_token(conn, db)
        date_str = session.started_at.date().isoformat()

        if needs_recovery:
            rec = await fetch_whoop_recovery(token, date_str)
            if rec:
                rec_score = rec.get("score", {}) or {}
                if session.recovery_score is None:
                    session.recovery_score = rec_score.get("recovery_score")
                if session.hrv_rmssd is None:
                    hrv = rec_score.get("hrv_rmssd_milli")
                    if hrv is not None:
                        session.hrv_rmssd = hrv / 1000.0

        if needs_sleep:
            sleep = await fetch_whoop_sleep(token, date_str)
            hrs, perf = extract_sleep_metrics(sleep)
            if session.sleep_hours is None and hrs is not None:
                session.sleep_hours = hrs
            if session.sleep_performance is None and perf is not None:
                session.sleep_performance = perf

        await db.commit()
    except Exception:
        logger.exception("Failed to enrich session %s with daily Whoop data", session.id)
