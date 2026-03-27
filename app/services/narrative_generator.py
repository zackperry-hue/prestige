"""Generate AI-powered workout narrative summaries using Claude.

Produces a conversational, coaching-style paragraph that synthesizes
workout data, compares to history, and offers actionable recovery advice.
Similar to Whoop's AI coach summaries.
"""

import logging
from datetime import date, datetime, timedelta

import anthropic

from app.config import settings
from app.models.user_profile import UserProfile
from app.models.workout_session import WorkoutSession
from app.services.workout_insights import WorkoutHighlights

logger = logging.getLogger(__name__)


def _format_duration_natural(seconds: int | None) -> str:
    """Format duration as '1:31' or '45 min'."""
    if not seconds:
        return "unknown duration"
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}:{mins:02d} hrs"
    return f"{mins} min"


def _build_profile_context(profile: UserProfile | None) -> str:
    """Build athlete profile context from onboarding questionnaire."""
    if not profile:
        return ""

    lines = ["\nAthlete profile:"]

    if profile.fitness_goals:
        goals = [g.replace("_", " ") for g in profile.fitness_goals.split(",")]
        lines.append(f"- Goals: {', '.join(goals)}")

    if profile.experience_level:
        lines.append(f"- Experience level: {profile.experience_level}")

    if profile.primary_sports:
        sports = profile.primary_sports.split(",")
        lines.append(f"- Primary sports: {', '.join(sports)}")

    if profile.weekly_target:
        lines.append(f"- Weekly training target: {profile.weekly_target} days/week")

    if profile.target_event_name:
        event_line = f"- Target event: {profile.target_event_name}"
        if profile.target_event_date:
            try:
                event_date = datetime.strptime(profile.target_event_date, "%Y-%m-%d").date()
                days_out = (event_date - date.today()).days
                if days_out > 0:
                    weeks_out = days_out // 7
                    event_line += f" ({days_out} days / {weeks_out} weeks away)"
                elif days_out == 0:
                    event_line += " (TODAY!)"
                else:
                    event_line += " (past)"
            except ValueError:
                pass
        lines.append(event_line)

    if profile.additional_context:
        lines.append(f"- Additional context from athlete: {profile.additional_context}")

    return "\n".join(lines)


def _build_workout_context(
    session: WorkoutSession,
    highlights: WorkoutHighlights,
    user_name: str,
    units: str = "imperial",
    profile: UserProfile | None = None,
) -> str:
    """Build a structured context block for Claude from session data."""
    lines = [
        f"Athlete name: {user_name}",
        f"Sport: {session.sport_type or 'workout'}",
        f"Platforms: {session.platforms}",
        f"Duration: {_format_duration_natural(session.duration_seconds)}",
    ]

    if session.distance_meters:
        if units == "imperial":
            dist = session.distance_meters / 1609.34
            lines.append(f"Distance: {dist:.1f} miles")
        else:
            dist = session.distance_meters / 1000
            lines.append(f"Distance: {dist:.1f} km")

    if session.calories:
        lines.append(f"Calories: {int(session.calories)} kcal")
    if session.avg_heart_rate:
        lines.append(f"Avg heart rate: {int(session.avg_heart_rate)} bpm")
    if session.max_heart_rate:
        lines.append(f"Max heart rate: {int(session.max_heart_rate)} bpm")
    if session.strain_score:
        lines.append(f"Whoop strain: {session.strain_score:.1f}")
    if session.recovery_score is not None:
        lines.append(f"Whoop recovery: {int(session.recovery_score)}%")
    if session.hrv_rmssd is not None:
        lines.append(f"HRV (RMSSD): {int(session.hrv_rmssd)} ms")
    if session.elevation_gain:
        if units == "imperial":
            lines.append(f"Elevation gain: {int(session.elevation_gain * 3.28084)} ft")
        else:
            lines.append(f"Elevation gain: {int(session.elevation_gain)} m")
    if session.avg_power_watts:
        lines.append(f"Avg power: {int(session.avg_power_watts)} W")

    # Add historical context from insights
    if highlights.insights:
        lines.append("\nComparisons to recent history:")
        for insight in highlights.insights:
            lines.append(f"- {insight.label}: {insight.message}")

    if highlights.streak_days and highlights.streak_days >= 2:
        lines.append(f"Current streak: {highlights.streak_days} days")
    if highlights.total_workouts_this_week:
        lines.append(f"Workouts this week: {highlights.total_workouts_this_week}")
    if highlights.total_workouts_this_month:
        lines.append(f"Workouts this month: {highlights.total_workouts_this_month}")

    # Add athlete profile context from onboarding
    profile_context = _build_profile_context(profile)
    if profile_context:
        lines.append(profile_context)

    return "\n".join(lines)


SYSTEM_PROMPT = """You are a concise, knowledgeable fitness coach writing a post-workout email summary.
Your tone is direct, encouraging, and data-driven — like a coach who knows the athlete well.

Write 2-3 short paragraphs:
1. Lead with the headline takeaway about this workout — what stands out, what it means for their fitness. Reference specific numbers naturally (don't just list them). Compare to their recent history when available.
2. Connect the workout to the athlete's stated goals and training context (if profile data is provided). For example, if they're training for a specific event, relate this workout to their preparation. If they want to get faster, note pace trends.
3. Give one actionable recovery or training recommendation based on the workout intensity and their goals.

Rules:
- Use the athlete's first name once at the start
- Keep it under 150 words total
- No bullet points or lists — flowing paragraphs only
- No generic praise — be specific about what the data shows
- If multi-platform data is available, note what the combined view reveals
- If the athlete has a target event, weave in how this workout fits their preparation timeline
- If the athlete has a weekly training target, reference their progress toward it
- If experience level is provided, match your coaching tone accordingly (simpler for beginners, more technical for advanced)
- Don't repeat data that will be shown in the stats section below
- No sign-off or greeting — this drops into the middle of an email template"""


async def generate_workout_narrative(
    session: WorkoutSession,
    highlights: WorkoutHighlights,
    user_name: str,
    units: str = "imperial",
    profile: UserProfile | None = None,
) -> str | None:
    """Generate a Claude-powered narrative summary for a workout session.

    Returns the narrative text, or None if generation fails.
    """
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set, skipping narrative generation")
        return None

    context = _build_workout_context(session, highlights, user_name, units, profile=profile)

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Write a post-workout summary for this session:\n\n{context}",
                }
            ],
        )
        narrative = message.content[0].text.strip()
        logger.info("Generated workout narrative (%d chars)", len(narrative))
        return narrative

    except Exception:
        logger.exception("Failed to generate workout narrative")
        return None
