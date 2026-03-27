"""Whoop API client and workout normalizer."""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import PlatformConnection
from app.platforms.sport_type_map import normalize_sport_type
from app.schemas.workout import NormalizedWorkout
from app.services.token_manager import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"


async def refresh_whoop_token(conn: PlatformConnection, db: AsyncSession) -> str:
    """Refresh an expired Whoop access token."""
    if not conn.refresh_token_enc:
        raise RuntimeError("No refresh token available for Whoop connection")

    refresh_token = decrypt_token(conn.refresh_token_enc)

    from app.config import settings

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            WHOOP_TOKEN_URL,
            data={
                "client_id": settings.whoop_client_id,
                "client_secret": settings.whoop_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

    if resp.status_code != 200:
        logger.error("Whoop token refresh failed: %s", resp.text)
        conn.is_active = False
        await db.commit()
        raise RuntimeError("Failed to refresh Whoop token")

    data = resp.json()
    conn.access_token_enc = encrypt_token(data["access_token"])
    if data.get("refresh_token"):
        conn.refresh_token_enc = encrypt_token(data["refresh_token"])
    conn.token_expires_at = datetime.now(UTC) + timedelta(seconds=data.get("expires_in", 3600))
    await db.commit()

    return data["access_token"]


async def get_whoop_token(conn: PlatformConnection, db: AsyncSession) -> str:
    """Get a valid access token, refreshing if expired."""
    if conn.token_expires_at and conn.token_expires_at < datetime.now(UTC) + timedelta(minutes=5):
        return await refresh_whoop_token(conn, db)
    return decrypt_token(conn.access_token_enc)


async def fetch_whoop_workout(workout_id: str, access_token: str) -> dict:
    """Fetch a single workout from the Whoop API v2."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{WHOOP_API_BASE}/activity/workout/{workout_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        logger.error("Whoop workout fetch failed: %s %s", resp.status_code, resp.text)
        raise RuntimeError(f"Failed to fetch Whoop workout {workout_id}")
    return resp.json()


def normalize_whoop_workout(data: dict) -> NormalizedWorkout:
    """Convert a Whoop workout into a NormalizedWorkout."""
    start = datetime.fromisoformat(data["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(data["end"].replace("Z", "+00:00")) if data.get("end") else None
    duration = int((end - start).total_seconds()) if end else 0

    score = data.get("score", {})
    sport_id = data.get("sport_id", -1)

    return NormalizedWorkout(
        platform="whoop",
        platform_workout_id=str(data["id"]),
        sport_type=normalize_sport_type("whoop", sport_id),
        started_at=start,
        ended_at=end,
        duration_seconds=duration,
        distance_meters=score.get("distance_meter"),
        calories=score.get("kilojoule", 0) * 0.239006 if score.get("kilojoule") else None,
        avg_heart_rate=score.get("average_heart_rate"),
        max_heart_rate=score.get("max_heart_rate"),
        strain_score=score.get("strain"),
        raw_data=data,
    )


async def get_connection_by_whoop_user(
    whoop_user_id: str, db: AsyncSession
) -> PlatformConnection | None:
    """Look up a Whoop connection by Whoop user ID."""
    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.platform == "whoop",
            PlatformConnection.platform_user_id == whoop_user_id,
            PlatformConnection.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()
