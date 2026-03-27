"""Garmin Connect client and workout normalizer.

Uses python-garminconnect library (credential-based auth) for testing.
Will migrate to official Garmin Connect Developer Program API (OAuth 2.0 PKCE)
when approved.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

from garminconnect import Garmin
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import PlatformConnection
from app.platforms.sport_type_map import normalize_sport_type
from app.schemas.workout import NormalizedWorkout
from app.services.token_manager import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)


def _create_garmin_client(conn: PlatformConnection) -> Garmin:
    """Create an authenticated Garmin client from stored credentials."""
    token_data = json.loads(decrypt_token(conn.access_token_enc))

    if "email" in token_data and "password" in token_data:
        client = Garmin(token_data["email"], token_data["password"])
        client.login()
        return client

    # Restore from saved session tokens (garth tokens)
    client = Garmin()
    client.garth.loads(token_data.get("garth_tokens", ""))
    client.display_name = token_data.get("display_name", "")
    return client


async def save_garmin_session(conn: PlatformConnection, client: Garmin, db: AsyncSession):
    """Save Garmin session tokens for reuse (avoids re-login)."""
    token_data = {
        "garth_tokens": client.garth.dumps(),
        "display_name": client.display_name,
    }
    conn.access_token_enc = encrypt_token(json.dumps(token_data))
    await db.commit()


def fetch_garmin_activities(client: Garmin, start_date: str, end_date: str) -> list[dict]:
    """Fetch activities from Garmin Connect for a date range.

    Args:
        client: Authenticated Garmin client
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        List of activity dicts
    """
    try:
        activities = client.get_activities_by_date(start_date, end_date)
        return activities or []
    except Exception:
        logger.exception("Failed to fetch Garmin activities")
        return []


def normalize_garmin_activity(data: dict) -> NormalizedWorkout:
    """Convert a Garmin activity into a NormalizedWorkout."""
    # Parse start time
    start_str = data.get("startTimeLocal") or data.get("startTimeGMT", "")
    if start_str:
        # Garmin returns ISO format like "2026-03-27 17:30:00"
        try:
            started_at = datetime.fromisoformat(start_str.replace(" ", "T"))
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
        except ValueError:
            started_at = datetime.now(UTC)
    else:
        started_at = datetime.now(UTC)

    # Duration in seconds
    duration = data.get("duration", 0) or 0
    duration_seconds = int(float(duration))
    ended_at = started_at + timedelta(seconds=duration_seconds) if duration_seconds else None

    # Activity type
    activity_type = data.get("activityType", {})
    type_key = activity_type.get("typeKey", "") if isinstance(activity_type, dict) else str(activity_type)

    return NormalizedWorkout(
        platform="garmin",
        platform_workout_id=str(data.get("activityId", data.get("activityID", ""))),
        sport_type=normalize_sport_type("garmin", type_key),
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        distance_meters=data.get("distance"),
        calories=data.get("calories"),
        avg_heart_rate=data.get("averageHR"),
        max_heart_rate=data.get("maxHR"),
        elevation_gain=data.get("elevationGain"),
        avg_power_watts=data.get("avgPower"),
        raw_data=data,
    )
