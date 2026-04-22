"""Generate AI-powered workout narrative summaries using Claude.

Produces a conversational, coaching-style paragraph that synthesizes
workout data, compares to history, and offers actionable recovery advice.
Similar to Whoop's AI coach summaries.
"""

import logging
import uuid
from datetime import date, datetime, timedelta

import anthropic
import markdown as _markdown
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.insight_log import InsightLog
from app.models.user_profile import UserProfile
from app.models.workout_session import WorkoutSession
from app.services.workout_insights import WorkoutHighlights

logger = logging.getLogger(__name__)


def _narrative_to_html(text: str) -> str:
    """Convert the model's markdown narrative into email-safe HTML.

    The email template renders `narrative` with Jinja's autoescape on, so
    the raw markdown (** for bold, - for bullets) would otherwise show
    literally. We convert here so the template can pass through with
    `|safe` and all the sanitization responsibility stays in this module.
    """
    return _markdown.markdown(text, extensions=["extra"], output_format="html5")


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


# Sports where speed (mph / km/h) is the conventional metric rather than pace.
_SPEED_SPORTS = {
    "cycling", "ride", "virtual_ride", "mountain_biking",
    "gravel_cycling", "e_bike_ride",
}


def _build_workout_context(
    session: WorkoutSession,
    highlights: WorkoutHighlights,
    user_name: str,
    units: str = "imperial",
    profile: UserProfile | None = None,
) -> str:
    """Build a structured context block for Claude from session data.

    Does not include platform/source attribution — the user-facing insight
    should not mention which device or service the data came from.
    """
    today = date.today()
    day_name = today.strftime("%A")
    tomorrow_name = (today + timedelta(days=1)).strftime("%A")
    sport = (session.sport_type or "workout").lower()
    lines = [
        f"Athlete name: {user_name}",
        f"Today: {day_name} ({today.isoformat()}), tomorrow is {tomorrow_name}",
        f"Sport: {session.sport_type or 'workout'}",
        f"Duration: {_format_duration_natural(session.duration_seconds)}",
    ]

    if session.distance_meters:
        if units == "imperial":
            dist = session.distance_meters / 1609.34
            lines.append(f"Distance: {dist:.1f} miles")
        else:
            dist = session.distance_meters / 1000
            lines.append(f"Distance: {dist:.1f} km")

        # For speed-biased sports (cycling), include average speed. Pace is
        # meaningless on the bike; speed is the conventional metric.
        if sport in _SPEED_SPORTS and session.duration_seconds:
            hours = session.duration_seconds / 3600
            if hours > 0:
                if units == "imperial":
                    miles = session.distance_meters / 1609.34
                    lines.append(f"Average speed: {miles / hours:.1f} mph")
                else:
                    km = session.distance_meters / 1000
                    lines.append(f"Average speed: {km / hours:.1f} km/h")

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

## Output format

Produce exactly this structure, with blank lines as shown. Use plain markdown only — bold for the three section headers. No emojis, no horizontal rules, no decorative characters, no other headings, no sign-off, no greeting, no title prefix (do not write "WORKOUT INSIGHT" or similar), and no em-dash separating a header from its body.

**What happened**
[single paragraph of prose]

**What it means**
[single paragraph of prose]

**What to do next**
[single paragraph of prose]

Rules for each section:

- Each of the three sections is exactly one paragraph of prose. No bulleted or numbered lists anywhere. If the input includes a `Comparisons to recent history` block, weave the relevant comparisons into the "What happened" paragraph as sentences, not as a list.
- "What happened" is a plain-prose recap: duration, distance, avg HR, and — where the input provides it — average speed or pace. Include the one or two most meaningful comparisons from the history block as additional sentences.
- Classify session type (recovery / endurance / tempo / threshold / VO2 / unclear) only if HR-zone or power-zone data is present in the input. Otherwise say "unclear" or omit the classification. Raw avg/max HR alone is not enough.
- "What it means" interprets the session in the context of its purpose. If nothing about this session is notable relative to recent sessions, write: "This was a typical [session type] [sport] consistent with recent training." Do not manufacture insight.
- "What to do next" follows the recovery-data rule below.

## Sources and attribution

- Never mention the data source, platform, device, or brand (Whoop, Strava, Wahoo, Garmin, Apple Watch, etc.). Do not write "via Whoop", "from Strava", or "your watch says". The athlete does not need to see where the data came from.
- Treat all fields in the input as simply "your data" regardless of which platform populated them.

## Recovery guidance

If at least one of HRV (RMSSD), Whoop recovery score, sleep, resting HR, or RPE is present in the input, use that signal to give specific guidance.

If none of those are present, produce guidance in exactly this shape:

"Connect HRV, sleep, or RPE data for recovery-specific guidance. Based on heart rate alone, this session appears [moderate / moderate-to-hard / hard]; plan the next session's intensity accordingly."

You must NOT use any of these phrases or their variants, even as a second sentence:
- "monitor how you feel"
- "listen to your body"
- "see how you recover"
- "adjust based on how your legs feel"
- any other variant asking the athlete to self-judge recovery in the absence of data.

## Arithmetic

- Compute every numerical comparison from the raw input values. Do not estimate.
- Verify each percentage against the underlying numbers in the input (duration, distance, avg HR, calories, power). Use (new - old) / old × 100.
- State duration, distance, calorie, and power comparisons as percentages only — e.g. "45% shorter than your last ride." Do not mix an absolute difference and a percentage in the same claim.
- State heart-rate comparisons in absolute bpm — e.g. "12 bpm higher than last ride." Percentages of HR are not physiologically meaningful. This is the only exception to the percentage-only rule.
- If the input provides a pre-computed comparison (in `Comparisons to recent history`), treat it as a source to verify against, not as final copy — re-derive the percentage before using it.

## Hard rules

- Never describe a workout as a "breakthrough," "standout," "massive step up," or similar unless a defined personal best is present in the input.
- Do NOT reference streaks, workout counts, monthly totals, or any other gamification metrics. They are not coaching signals. Focus on training load, intensity, and session purpose.
- Use second person ("you") throughout. Do not use the athlete's first name anywhere in the output. Do not mix second and third person in the same insight.
- Do not label session intensity (tempo, threshold, VO2) unless HR-zone or power-zone data is present.
- Do not reference the day of the week unless it's materially relevant to guidance.
- Length: 80–150 words total across all three sections. Shorter is better when data is thin.
- Tone: direct, specific, professional. No motivational language. No exclamation points.

When data is insufficient: produce a short insight acknowledging what's missing. A two-sentence honest output beats a five-paragraph confident one."""


_MODEL_ID = "claude-sonnet-4-20250514"


def _session_payload_snapshot(session: WorkoutSession) -> dict:
    """Capture the raw session fields that feed the prompt, for persistent logging.

    Kept separate from the model-facing context string so it's structured and
    queryable. Platform attribution lives here (for internal debugging) but
    not in the prompt or user-facing output.
    """
    return {
        "session_id": str(getattr(session, "id", "")) or None,
        "sport_type": session.sport_type,
        "platforms": session.platforms,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "duration_seconds": session.duration_seconds,
        "distance_meters": session.distance_meters,
        "calories": session.calories,
        "avg_heart_rate": session.avg_heart_rate,
        "max_heart_rate": session.max_heart_rate,
        "strain_score": session.strain_score,
        "recovery_score": session.recovery_score,
        "hrv_rmssd": session.hrv_rmssd,
        "elevation_gain": session.elevation_gain,
        "avg_power_watts": session.avg_power_watts,
    }


async def _persist_insight_log(
    db: AsyncSession | None,
    insight_id: uuid.UUID,
    session: WorkoutSession,
    payload: dict,
    user_prompt: str,
    output_md: str | None,
    status: str,
    error: str | None = None,
) -> None:
    """Persist one generation attempt to the insight_logs table.

    Best-effort: a logging failure must not break the email send path.
    """
    if db is None:
        return
    try:
        row = InsightLog(
            id=insight_id,
            session_id=getattr(session, "id", None),
            user_id=getattr(session, "user_id", None),
            model=_MODEL_ID,
            input_payload=payload,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            output_markdown=output_md,
            input_chars=len(user_prompt),
            output_chars=len(output_md) if output_md else 0,
            status=status,
            error_message=error,
        )
        db.add(row)
        await db.commit()
    except Exception:
        logger.exception("failed to persist insight_log %s", insight_id)


async def generate_workout_narrative(
    session: WorkoutSession,
    highlights: WorkoutHighlights,
    user_name: str,
    units: str = "imperial",
    profile: UserProfile | None = None,
    db: AsyncSession | None = None,
) -> str | None:
    """Generate a Claude-powered narrative summary for a workout session.

    Returns the narrative text, or None if generation fails.

    When a db session is supplied, persists an `insight_logs` row capturing
    the full input payload, prompt, and output with a unique insight_id.
    """
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set, skipping narrative generation")
        return None

    insight_id = uuid.uuid4()
    context = _build_workout_context(session, highlights, user_name, units, profile=profile)
    user_prompt = f"Write a post-workout summary for this session:\n\n{context}"
    payload = _session_payload_snapshot(session)

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model=_MODEL_ID,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        narrative_md = message.content[0].text.strip()
        narrative_html = _narrative_to_html(narrative_md)
        logger.info(
            "narrative_generated insight_id=%s session=%s user=%s input_chars=%d output_chars=%d",
            insight_id,
            getattr(session, "id", "?"),
            user_name,
            len(user_prompt),
            len(narrative_md),
        )
        await _persist_insight_log(
            db, insight_id, session, payload, user_prompt, narrative_md, status="ok"
        )
        return narrative_html

    except Exception as exc:
        logger.exception(
            "narrative_generation_failed insight_id=%s session=%s user=%s",
            insight_id,
            getattr(session, "id", "?"),
            user_name,
        )
        await _persist_insight_log(
            db, insight_id, session, payload, user_prompt, None,
            status="error", error=str(exc),
        )
        return None
