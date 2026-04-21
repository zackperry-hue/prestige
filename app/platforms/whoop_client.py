"""Whoop API client and workout normalizer."""

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

WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"


async def refresh_whoop_token(conn: PlatformConnection, db: AsyncSession) -> str:
    """Refresh an expired Whoop access token."""
    if not conn.refresh_token_enc:
        raise RuntimeError("No refresh token available for Whoop connection")

    refresh_token = decrypt_token(conn.refresh_token_enc)

    from app.config import settings

    async with httpx.AsyncClient(timeout=15.0) as client:
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
        logger.error("Whoop token refresh failed (status %s): %s", resp.status_code, redact_secrets(resp.text))
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
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{WHOOP_API_BASE}/activity/workout/{workout_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        logger.error("Whoop workout fetch failed (status %s): %s", resp.status_code, redact_secrets(resp.text))
        raise RuntimeError(f"Failed to fetch Whoop workout {workout_id}")
    return resp.json()


async def fetch_whoop_workouts(
    access_token: str,
    start: datetime,
    end: datetime,
    limit: int = 50,
    max_pages: int = 10,
) -> list[dict]:
    """Fetch workouts in a time range from Whoop API v2 with pagination."""
    all_workouts: list[dict] = []
    next_token: str | None = None
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        for _ in range(max_pages):
            params: dict = {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": limit,
            }
            if next_token:
                params["nextToken"] = next_token

            resp = await client.get(f"{WHOOP_API_BASE}/activity/workout", params=params)

            if resp.status_code != 200:
                logger.error(
                    "Whoop workouts fetch failed (status %s): %s",
                    resp.status_code,
                    redact_secrets(resp.text),
                )
                break

            data = resp.json()
            records = data.get("records", [])
            all_workouts.extend(records)

            next_token = data.get("next_token")
            if not next_token or not records:
                break

    return all_workouts


async def fetch_whoop_recovery(access_token: str, start_date: str) -> dict | None:
    """Fetch recovery data for a specific date from Whoop API v2.

    start_date should be in YYYY-MM-DD format.
    Recovery includes recovery_score and hrv_rmssd.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{WHOOP_API_BASE}/recovery",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"start": f"{start_date}T00:00:00.000Z", "end": f"{start_date}T23:59:59.999Z"},
        )
    if resp.status_code != 200:
        logger.warning("Whoop recovery fetch failed (status %s): %s", resp.status_code, redact_secrets(resp.text))
        return None

    records = resp.json().get("records", [])
    if not records:
        return None

    # Return the most recent recovery for the day
    return records[0]


def normalize_whoop_workout(data: dict, recovery_data: dict | None = None) -> NormalizedWorkout:
    """Convert a Whoop workout into a NormalizedWorkout.

    If recovery_data is provided, it includes recovery_score and hrv_rmssd.
    """
    start = datetime.fromisoformat(data["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(data["end"].replace("Z", "+00:00")) if data.get("end") else None
    duration = int((end - start).total_seconds()) if end else 0

    score = data.get("score", {})
    sport_id = data.get("sport_id", -1)

    # Extract recovery metrics if available
    recovery_score = None
    hrv_rmssd = None
    if recovery_data:
        rec_score = recovery_data.get("score", {})
        recovery_score = rec_score.get("recovery_score")
        hrv_rmssd = rec_score.get("hrv_rmssd_milli")
        if hrv_rmssd is not None:
            hrv_rmssd = hrv_rmssd / 1000.0  # Convert from milliseconds to ms (RMSSD)

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
        recovery_score=recovery_score,
        hrv_rmssd=hrv_rmssd,
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
