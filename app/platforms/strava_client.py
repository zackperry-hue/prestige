"""Strava API client and workout normalizer."""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import PlatformConnection
from app.platforms.sport_type_map import normalize_sport_type
from app.schemas.workout import NormalizedWorkout
from app.services.log_redaction import redact_secrets
from app.services.token_manager import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


async def refresh_strava_token(conn: PlatformConnection, db: AsyncSession) -> str:
    """Refresh an expired Strava access token. Returns the new access token."""
    refresh_token = decrypt_token(conn.refresh_token_enc)

    from app.config import settings

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

    if resp.status_code != 200:
        logger.error("Strava token refresh failed (status %s): %s", resp.status_code, redact_secrets(resp.text))
        conn.is_active = False
        await db.commit()
        raise RuntimeError("Failed to refresh Strava token")

    data = resp.json()
    conn.access_token_enc = encrypt_token(data["access_token"])
    conn.refresh_token_enc = encrypt_token(data["refresh_token"])
    conn.token_expires_at = datetime.fromtimestamp(data["expires_at"], tz=UTC)
    await db.commit()

    return data["access_token"]


async def get_strava_token(conn: PlatformConnection, db: AsyncSession) -> str:
    """Get a valid access token, refreshing if expired."""
    if conn.token_expires_at and conn.token_expires_at < datetime.now(UTC) + timedelta(minutes=5):
        return await refresh_strava_token(conn, db)
    return decrypt_token(conn.access_token_enc)


async def fetch_strava_activity(activity_id: int | str, access_token: str) -> dict:
    """Fetch a single activity from the Strava API."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{STRAVA_API_BASE}/activities/{activity_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        logger.error("Strava activity fetch failed (status %s): %s", resp.status_code, redact_secrets(resp.text))
        raise RuntimeError(f"Failed to fetch Strava activity {activity_id}")
    return resp.json()


def normalize_strava_activity(data: dict) -> NormalizedWorkout:
    """Convert a Strava activity into a NormalizedWorkout."""
    started_at = datetime.fromisoformat(data["start_date"].replace("Z", "+00:00"))
    elapsed_time = data.get("elapsed_time", data.get("moving_time", 0))

    return NormalizedWorkout(
        platform="strava",
        platform_workout_id=str(data["id"]),
        sport_type=normalize_sport_type("strava", data.get("type", "Workout")),
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=elapsed_time) if elapsed_time else None,
        duration_seconds=elapsed_time,
        distance_meters=data.get("distance"),
        calories=data.get("calories"),
        avg_heart_rate=data.get("average_heartrate"),
        max_heart_rate=data.get("max_heartrate"),
        elevation_gain=data.get("total_elevation_gain"),
        avg_power_watts=data.get("average_watts"),
        raw_data=data,
    )


async def get_connection_by_athlete_id(
    athlete_id: str, db: AsyncSession
) -> PlatformConnection | None:
    """Look up a Strava connection by athlete ID."""
    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.platform == "strava",
            PlatformConnection.platform_user_id == athlete_id,
            PlatformConnection.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()
