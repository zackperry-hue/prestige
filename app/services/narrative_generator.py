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
    today = date.today()
    day_name = today.strftime("%A")
    tomorrow_name = (today + timedelta(days=1)).strftime("%A")
    lines = [
        f"Athlete name: {user_name}",
        f"Today: {day_name} ({today.isoformat()}), tomorrow is {tomorrow_name}",
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


SYSTEM_PROMPT = """You are generating a post-workout insight for an athlete using Prestige Fit. Your job is to be an honest coach, not a cheerleader. Follow these rules strictly.

The sport is given to you in the `Sport:` field. Tailor language to that sport — do not assume cycling.

Structure the output in three labeled sections:

**What happened** — State the facts. Session type (recovery / endurance / tempo / threshold / VO2 / unclear), duration, distance, average HR, and any computed comparisons to the athlete's recent trend. Only cite a comparison that appears verbatim in the `Comparisons to recent history` block in the input — do not compute, estimate, rephrase, or round deltas yourself. If a field is missing, omit it — do not estimate.

**What it means** — Interpret the session in the context of its purpose. A zone-2 endurance session should be evaluated as a zone-2 session, not graded against a threshold effort. If the session type is unclear from the data, say so. If nothing about this session is notable relative to recent sessions, say "This was a typical [session type] [sport] consistent with recent training." Do not manufacture insight.

**What to do next** — Only provide recovery or training guidance if the data supports it. Recovery guidance requires at least one of: HRV (RMSSD), Whoop recovery score, sleep, resting HR, or athlete-reported RPE. If none of those are present, write: "No recovery guidance available without HRV, recovery score, sleep, or subjective effort data." Generic advice like "eat protein and sleep well" is forbidden.

Hard rules:
- Never describe a workout as a "breakthrough," "standout," "massive step up," or similar unless the numbers genuinely support it (e.g., a personal best on a defined metric present in the input).
- Every numerical comparison must be copied verbatim from the `Comparisons to recent history` block. If you are unsure, omit it.
- Do not label session intensity (tempo, threshold, VO2) unless HR-zone or power-zone data is in the input. Raw avg/max HR alone is not enough — classify as "unclear" in that case.
- Do not reference the day of the week unless it's materially relevant to guidance.
- Length: 80–150 words total across all three sections. Shorter is better when data is thin.
- Tone: direct, specific, professional. No motivational language. No exclamation points.
- Use the athlete's first name once at the start, then drop it.
- No sign-off or greeting — this drops into the middle of an email template.
- Do not repeat raw stats (duration, distance, HR) that the email already shows in a stats table below your text; cite them only when they anchor a point.

When data is insufficient: produce a short insight acknowledging what's missing. A two-sentence honest output beats a five-paragraph confident one."""


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
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
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
        logger.info(
            "narrative_generated session=%s user=%s input_chars=%d output_chars=%d\n"
            "--- INPUT CONTEXT ---\n%s\n--- OUTPUT NARRATIVE ---\n%s\n--- END ---",
            getattr(session, "id", "?"),
            user_name,
            len(context),
            len(narrative),
            context,
            narrative,
        )
        return narrative

    except Exception:
        logger.exception(
            "narrative_generation_failed session=%s user=%s\n--- INPUT CONTEXT ---\n%s\n--- END ---",
            getattr(session, "id", "?"),
            user_name,
            context,
        )
        return None
