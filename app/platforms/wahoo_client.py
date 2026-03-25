"""Wahoo Cloud API client and workout normalizer."""

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

WAHOO_API_BASE = "https://api.wahooligan.com/v1"
WAHOO_TOKEN_URL = "https://api.wahooligan.com/oauth/token"


async def refresh_wahoo_token(conn: PlatformConnection, db: AsyncSession) -> str:
    """Refresh an expired Wahoo access token."""
    if not conn.refresh_token_enc:
        raise RuntimeError("No refresh token available for Wahoo connection")

    refresh_token = decrypt_token(conn.refresh_token_enc)

    from app.config import settings

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            WAHOO_TOKEN_URL,
            data={
                "client_id": settings.wahoo_client_id,
                "client_secret": settings.wahoo_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

    if resp.status_code != 200:
        logger.error("Wahoo token refresh failed: %s", resp.text)
        conn.is_active = False
        await db.commit()
        raise RuntimeError("Failed to refresh Wahoo token")

    data = resp.json()
    conn.access_token_enc = encrypt_token(data["access_token"])
    if data.get("refresh_token"):
        conn.refresh_token_enc = encrypt_token(data["refresh_token"])
    conn.token_expires_at = datetime.now(UTC) + timedelta(seconds=data.get("expires_in", 7200))
    await db.commit()

    return data["access_token"]


async def get_wahoo_token(conn: PlatformConnection, db: AsyncSession) -> str:
    """Get a valid access token, refreshing if expired."""
    if conn.token_expires_at and conn.token_expires_at < datetime.now(UTC) + timedelta(minutes=5):
        return await refresh_wahoo_token(conn, db)
    return decrypt_token(conn.access_token_enc)


async def fetch_wahoo_workouts(
    access_token: str,
    created_after: datetime | None = None,
    page: int = 1,
    per_page: int = 50,
) -> list[dict]:
    """Fetch workouts from Wahoo API. Returns list of workout dicts."""
    params: dict = {"page": page, "per_page": per_page}
    if created_after:
        params["created_after"] = created_after.isoformat()

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{WAHOO_API_BASE}/workouts",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )

    if resp.status_code != 200:
        logger.error("Wahoo workouts fetch failed: %s %s", resp.status_code, resp.text)
        raise RuntimeError("Failed to fetch Wahoo workouts")

    data = resp.json()
    return data.get("workouts", data) if isinstance(data, dict) else data


def normalize_wahoo_workout(data: dict) -> NormalizedWorkout:
    """Convert a Wahoo workout into a NormalizedWorkout."""
    started_at_raw = data.get("starts") or data.get("created_at", "")
    started_at = datetime.fromisoformat(started_at_raw.replace("Z", "+00:00"))

    summary = data.get("workout_summary", {}) or {}
    duration = summary.get("duration_active_accum") or summary.get("duration_total_accum") or 0
    ended_at = started_at + timedelta(seconds=int(duration)) if duration else None

    workout_type_id = data.get("workout_type_id", 0)

    return NormalizedWorkout(
        platform="wahoo",
        platform_workout_id=str(data["id"]),
        sport_type=normalize_sport_type("wahoo", workout_type_id),
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=int(duration),
        distance_meters=summary.get("distance_accum"),
        calories=summary.get("calories_accum"),
        avg_heart_rate=summary.get("heart_rate_avg"),
        max_heart_rate=summary.get("heart_rate_max"),
        elevation_gain=summary.get("ascent_accum"),
        avg_power_watts=summary.get("power_avg"),
        raw_data=data,
    )
