"""Generate workout highlights by comparing against historical data."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workout import Workout
from app.models.workout_session import WorkoutSession
from app.schemas.workout import NormalizedWorkout

logger = logging.getLogger(__name__)


@dataclass
class Insight:
    label: str  # e.g. "Duration"
    message: str  # e.g. "3:12 faster than your last run"
    direction: str  # "up", "down", "neutral"


@dataclass
class WorkoutHighlights:
    insights: list[Insight] = field(default_factory=list)
    vs_last: dict = field(default_factory=dict)  # comparison to last same-type workout
    vs_avg_30d: dict = field(default_factory=dict)  # comparison to 30-day average
    total_workouts_this_week: int = 0
    total_workouts_this_month: int = 0
    streak_days: int = 0  # consecutive days with a workout


def _pct_change(current: float, previous: float) -> float:
    """Calculate percentage change. Positive = increase."""
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100


def _format_duration_delta(seconds: int) -> str:
    """Format a duration delta into a readable string."""
    abs_seconds = abs(seconds)
    if abs_seconds >= 3600:
        hours, remainder = divmod(abs_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours}h {minutes}m"
    if abs_seconds >= 60:
        minutes, secs = divmod(abs_seconds, 60)
        return f"{minutes}m {secs}s"
    return f"{abs_seconds}s"


def _format_pace(meters: float, seconds: int, units: str = "metric") -> float | None:
    """Calculate pace in min/km or min/mi. Returns None if no distance."""
    if not meters or meters <= 0 or seconds <= 0:
        return None
    if units == "imperial":
        miles = meters / 1609.34
        return (seconds / 60) / miles
    km = meters / 1000
    return (seconds / 60) / km


def _format_speed(meters: float, seconds: int, units: str = "imperial") -> float | None:
    """Calculate speed in mph or km/h. Returns None if no distance."""
    if not meters or meters <= 0 or seconds <= 0:
        return None
    hours = seconds / 3600
    if units == "imperial":
        miles = meters / 1609.34
        return miles / hours
    km = meters / 1000
    return km / hours


# Sports where pace (min/mi, min/km) makes sense
_PACE_SPORTS = {"running", "run", "trail_running", "walking", "walk", "hiking", "hike"}
# Sports where speed (mph, km/h) makes sense
_SPEED_SPORTS = {"cycling", "ride", "virtual_ride", "mountain_biking", "gravel_cycling", "e_bike_ride"}


async def generate_highlights(
    db: AsyncSession,
    user_id: uuid.UUID,
    workout: NormalizedWorkout,
    units: str = "imperial",
) -> WorkoutHighlights:
    """Generate insights by comparing this workout to the user's history."""
    highlights = WorkoutHighlights()
    now = datetime.now(UTC)

    # --- Fetch last workout of same sport type ---
    last_same_type = await db.execute(
        select(Workout)
        .where(
            Workout.user_id == user_id,
            Workout.sport_type == workout.sport_type,
            Workout.started_at < workout.started_at,
        )
        .order_by(Workout.started_at.desc())
        .limit(1)
    )
    prev = last_same_type.scalar_one_or_none()

    # --- Fetch 30-day averages for same sport type ---
    thirty_days_ago = now - timedelta(days=30)
    avg_result = await db.execute(
        select(
            func.avg(Workout.duration_seconds).label("avg_duration"),
            func.avg(Workout.distance_meters).label("avg_distance"),
            func.avg(Workout.calories).label("avg_calories"),
            func.avg(Workout.avg_heart_rate).label("avg_hr"),
            func.count(Workout.id).label("count"),
        ).where(
            Workout.user_id == user_id,
            Workout.sport_type == workout.sport_type,
            Workout.started_at >= thirty_days_ago,
        )
    )
    avgs = avg_result.one()

    # --- Weekly and monthly counts ---
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    week_count = await db.execute(
        select(func.count(WorkoutSession.id)).where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.started_at >= week_start,
        )
    )
    highlights.total_workouts_this_week = week_count.scalar() or 0

    month_count = await db.execute(
        select(func.count(WorkoutSession.id)).where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.started_at >= month_start,
        )
    )
    highlights.total_workouts_this_month = month_count.scalar() or 0

    # --- Streak calculation (consecutive days with any workout) ---
    day_col = func.date_trunc("day", Workout.started_at).label("day")
    recent_dates = await db.execute(
        select(day_col)
        .where(Workout.user_id == user_id)
        .group_by(day_col)
        .order_by(day_col.desc())
        .limit(60)
    )
    workout_days = [row.day.date() if hasattr(row.day, "date") else row.day for row in recent_dates]
    streak = 0
    check_date = now.date()
    for day in workout_days:
        if day == check_date or day == check_date - timedelta(days=1):
            streak += 1
            check_date = day - timedelta(days=1)
        else:
            break
    highlights.streak_days = streak

    # --- Generate insights vs last workout ---
    if prev:
        sport_display = workout.sport_type.replace("_", " ")

        # Duration comparison
        if workout.duration_seconds and prev.duration_seconds:
            delta = workout.duration_seconds - prev.duration_seconds
            delta_str = _format_duration_delta(delta)
            if delta < 0:
                highlights.insights.append(Insight(
                    label="Duration",
                    message=f"{delta_str} shorter than your last {sport_display}",
                    direction="down",
                ))
            elif delta > 0:
                highlights.insights.append(Insight(
                    label="Duration",
                    message=f"{delta_str} longer than your last {sport_display}",
                    direction="up",
                ))

        # Pace/speed comparison (sport-appropriate units)
        sport = (workout.sport_type or "").lower()
        if sport in _PACE_SPORTS:
            pace_unit = "min/mi" if units == "imperial" else "min/km"
            current_pace = _format_pace(workout.distance_meters, workout.duration_seconds, units)
            prev_pace = _format_pace(prev.distance_meters, prev.duration_seconds, units)
            if current_pace and prev_pace:
                pace_delta = current_pace - prev_pace
                if abs(pace_delta) > 0.05:
                    if pace_delta < 0:
                        highlights.insights.append(Insight(
                            label="Pace",
                            message=f"{abs(pace_delta):.2f} {pace_unit} faster than last time",
                            direction="up",
                        ))
                    else:
                        highlights.insights.append(Insight(
                            label="Pace",
                            message=f"{pace_delta:.2f} {pace_unit} slower than last time",
                            direction="down",
                        ))
        elif sport in _SPEED_SPORTS:
            speed_unit = "mph" if units == "imperial" else "km/h"
            current_speed = _format_speed(workout.distance_meters, workout.duration_seconds, units)
            prev_speed = _format_speed(prev.distance_meters, prev.duration_seconds, units)
            if current_speed and prev_speed:
                speed_delta = current_speed - prev_speed
                if abs(speed_delta) > 0.2:
                    if speed_delta > 0:
                        highlights.insights.append(Insight(
                            label="Speed",
                            message=f"{abs(speed_delta):.1f} {speed_unit} faster than last time",
                            direction="up",
                        ))
                    else:
                        highlights.insights.append(Insight(
                            label="Speed",
                            message=f"{abs(speed_delta):.1f} {speed_unit} slower than last time",
                            direction="down",
                        ))

        # Distance comparison
        if workout.distance_meters and prev.distance_meters and prev.distance_meters > 0:
            pct = _pct_change(workout.distance_meters, prev.distance_meters)
            if abs(pct) > 2:
                direction = "up" if pct > 0 else "down"
                word = "farther" if pct > 0 else "shorter"
                highlights.insights.append(Insight(
                    label="Distance",
                    message=f"{abs(pct):.0f}% {word} than your last {sport_display}",
                    direction=direction,
                ))

        # Heart rate comparison
        if workout.avg_heart_rate and prev.avg_heart_rate:
            hr_delta = workout.avg_heart_rate - prev.avg_heart_rate
            if abs(hr_delta) >= 3:
                if hr_delta < 0:
                    highlights.insights.append(Insight(
                        label="Heart Rate",
                        message=f"Avg HR {abs(hr_delta):.0f} bpm lower — better efficiency",
                        direction="up",
                    ))
                else:
                    highlights.insights.append(Insight(
                        label="Heart Rate",
                        message=f"Avg HR {hr_delta:.0f} bpm higher than last time",
                        direction="down",
                    ))

        # Calories comparison
        if workout.calories and prev.calories and prev.calories > 0:
            pct = _pct_change(workout.calories, prev.calories)
            if abs(pct) > 5:
                direction = "up" if pct > 0 else "down"
                highlights.insights.append(Insight(
                    label="Calories",
                    message=f"{abs(pct):.0f}% {'more' if pct > 0 else 'fewer'} calories burned",
                    direction=direction,
                ))

        # Strain comparison (Whoop)
        if workout.strain_score is not None and prev.strain_score is not None:
            strain_delta = workout.strain_score - prev.strain_score
            if abs(strain_delta) > 0.5:
                direction = "up" if strain_delta > 0 else "down"
                word = "higher" if strain_delta > 0 else "lower"
                highlights.insights.append(Insight(
                    label="Strain",
                    message=f"Strain {abs(strain_delta):.1f} {word} than last {sport_display}",
                    direction=direction,
                ))

        highlights.vs_last = {
            "date": prev.started_at,
            "duration_seconds": prev.duration_seconds,
            "distance_meters": prev.distance_meters,
            "avg_heart_rate": prev.avg_heart_rate,
            "calories": prev.calories,
        }

    # --- Insights vs 30-day average ---
    if avgs.count and avgs.count >= 3:  # need at least 3 workouts for meaningful average
        if workout.duration_seconds and avgs.avg_duration:
            pct = _pct_change(workout.duration_seconds, float(avgs.avg_duration))
            if abs(pct) > 10:
                direction = "up" if pct > 0 else "down"
                word = "longer" if pct > 0 else "shorter"
                highlights.insights.append(Insight(
                    label="30-Day Trend",
                    message=f"{abs(pct):.0f}% {word} than your 30-day average",
                    direction="neutral",
                ))

        if workout.avg_heart_rate and avgs.avg_hr:
            hr_diff = workout.avg_heart_rate - float(avgs.avg_hr)
            if abs(hr_diff) >= 5:
                word = "above" if hr_diff > 0 else "below"
                highlights.insights.append(Insight(
                    label="HR Trend",
                    message=f"Avg HR {abs(hr_diff):.0f} bpm {word} your 30-day average",
                    direction="down" if hr_diff > 0 else "up",
                ))

        highlights.vs_avg_30d = {
            "avg_duration": float(avgs.avg_duration) if avgs.avg_duration else None,
            "avg_distance": float(avgs.avg_distance) if avgs.avg_distance else None,
            "avg_hr": float(avgs.avg_hr) if avgs.avg_hr else None,
            "avg_calories": float(avgs.avg_calories) if avgs.avg_calories else None,
            "workout_count": avgs.count,
        }

    # --- First workout insight ---
    if not prev:
        sport_display = workout.sport_type.replace("_", " ").title()
        highlights.insights.append(Insight(
            label="First!",
            message=f"This is your first {sport_display} workout tracked",
            direction="neutral",
        ))

    # --- Streak insight ---
    if highlights.streak_days >= 3:
        highlights.insights.append(Insight(
            label="Streak",
            message=f"{highlights.streak_days}-day workout streak — keep it going!",
            direction="up",
        ))

    return highlights


async def generate_session_highlights(
    db: AsyncSession,
    user_id: uuid.UUID,
    session,  # WorkoutSession
    units: str = "imperial",
) -> WorkoutHighlights:
    """Generate insights for a merged session using the same logic as single workouts.

    Converts session data into a NormalizedWorkout-like object and reuses
    the existing generate_highlights logic.
    """
    # Build a pseudo-NormalizedWorkout from session fields
    pseudo_workout = NormalizedWorkout(
        platform=session.platforms.split(",")[0] if session.platforms else "unknown",
        platform_workout_id=str(session.id),
        sport_type=session.sport_type or "other",
        started_at=session.started_at,
        ended_at=session.ended_at,
        duration_seconds=session.duration_seconds or 0,
        distance_meters=session.distance_meters,
        calories=session.calories,
        avg_heart_rate=session.avg_heart_rate,
        max_heart_rate=session.max_heart_rate,
        strain_score=session.strain_score,
        elevation_gain=session.elevation_gain,
        avg_power_watts=session.avg_power_watts,
        raw_data={},
    )

    highlights = await generate_highlights(db, user_id, pseudo_workout, units=units)

    # Add recovery context if available from Whoop
    if session.recovery_score is not None:
        if session.recovery_score >= 67:
            highlights.insights.append(Insight(
                label="Recovery",
                message=f"You started this session at {session.recovery_score:.0f}% recovery — well rested",
                direction="up",
            ))
        elif session.recovery_score >= 34:
            highlights.insights.append(Insight(
                label="Recovery",
                message=f"Recovery was {session.recovery_score:.0f}% — moderate readiness",
                direction="neutral",
            ))
        else:
            highlights.insights.append(Insight(
                label="Recovery",
                message=f"Recovery was only {session.recovery_score:.0f}% — consider easier effort next time",
                direction="down",
            ))

    # HRV insight
    if session.hrv_rmssd is not None:
        highlights.insights.append(Insight(
            label="HRV",
            message=f"Pre-workout HRV was {session.hrv_rmssd:.0f} ms (RMSSD)",
            direction="neutral",
        ))

    return highlights
