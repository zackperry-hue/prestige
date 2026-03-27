"""Polls Garmin Connect for new activities every 5 minutes."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import async_session_factory
from app.models.connection import PlatformConnection
from app.platforms.garmin_client import (
    _create_garmin_client,
    fetch_garmin_activities,
    normalize_garmin_activity,
    save_garmin_session,
)
from app.services.workout_processor import process_workout

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(5)


async def _poll_single_connection(conn_id, user_id, last_poll_at):
    """Poll a single Garmin connection for new activities."""
    async with _semaphore:
        async with async_session_factory() as db:
            try:
                result = await db.execute(
                    select(PlatformConnection).where(PlatformConnection.id == conn_id)
                )
                conn = result.scalar_one_or_none()
                if not conn or not conn.is_active:
                    return

                client = _create_garmin_client(conn)

                since = last_poll_at or (datetime.now(UTC) - timedelta(hours=24))
                start_date = since.strftime("%Y-%m-%d")
                end_date = datetime.now(UTC).strftime("%Y-%m-%d")

                activities = fetch_garmin_activities(client, start_date, end_date)

                # Save refreshed session tokens
                await save_garmin_session(conn, client, db)

                new_count = 0
                for activity in activities:
                    activity_start = activity.get("startTimeLocal") or activity.get("startTimeGMT", "")
                    if activity_start:
                        try:
                            act_dt = datetime.fromisoformat(activity_start.replace(" ", "T"))
                            if act_dt.tzinfo is None:
                                act_dt = act_dt.replace(tzinfo=UTC)
                            if act_dt < since:
                                continue
                        except ValueError:
                            pass

                    normalized = normalize_garmin_activity(activity)
                    await process_workout(db, user_id, normalized)
                    new_count += 1

                conn.last_poll_at = datetime.now(UTC)
                await db.commit()

                if new_count:
                    logger.info(
                        "Polled %d new Garmin activities for user %s", new_count, user_id
                    )

            except Exception:
                logger.exception("Failed to poll Garmin for connection %s", conn_id)


async def poll_garmin_activities():
    """Main poller: fetch all active Garmin connections and poll for new activities."""
    logger.debug("Starting Garmin poll cycle")

    async with async_session_factory() as db:
        result = await db.execute(
            select(
                PlatformConnection.id,
                PlatformConnection.user_id,
                PlatformConnection.last_poll_at,
            ).where(
                PlatformConnection.platform == "garmin",
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

    logger.debug("Garmin poll cycle complete, checked %d connections", len(connections))
