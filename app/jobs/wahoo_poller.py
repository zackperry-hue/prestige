"""Polls Wahoo for new workouts every 5 minutes (no webhook support)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import async_session_factory
from app.models.connection import PlatformConnection
from app.platforms.wahoo_client import (
    fetch_wahoo_workouts,
    get_wahoo_token,
    normalize_wahoo_workout,
)
from app.services.workout_processor import process_workout

logger = logging.getLogger(__name__)

# Limit concurrent API calls to avoid overwhelming Wahoo
_semaphore = asyncio.Semaphore(10)


async def _poll_single_connection(conn_id, user_id, last_poll_at):
    """Poll a single Wahoo connection for new workouts."""
    async with _semaphore:
        async with async_session_factory() as db:
            try:
                result = await db.execute(
                    select(PlatformConnection).where(PlatformConnection.id == conn_id)
                )
                conn = result.scalar_one_or_none()
                if not conn or not conn.is_active:
                    return

                token = await get_wahoo_token(conn, db)
                since = last_poll_at or (datetime.now(UTC) - timedelta(hours=24))

                workouts = await fetch_wahoo_workouts(token, created_after=since)
                for w in workouts:
                    normalized = normalize_wahoo_workout(w)
                    await process_workout(db, user_id, normalized)

                conn.last_poll_at = datetime.now(UTC)
                await db.commit()

                if workouts:
                    logger.info(
                        "Polled %d new Wahoo workouts for user %s", len(workouts), user_id
                    )

            except Exception:
                logger.exception("Failed to poll Wahoo for connection %s", conn_id)


async def poll_wahoo_workouts():
    """Main poller: fetch all active Wahoo connections and poll for new workouts."""
    logger.debug("Starting Wahoo poll cycle")

    async with async_session_factory() as db:
        result = await db.execute(
            select(
                PlatformConnection.id,
                PlatformConnection.user_id,
                PlatformConnection.last_poll_at,
            ).where(
                PlatformConnection.platform == "wahoo",
                PlatformConnection.is_active.is_(True),
            )
        )
        connections = result.all()

    if not connections:
        return

    tasks = [
        _poll_single_connection(conn_id, user_id, last_poll_at)
        for conn_id, user_id, last_poll_at in connections
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    logger.debug("Wahoo poll cycle complete, checked %d connections", len(connections))
