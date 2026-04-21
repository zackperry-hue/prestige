"""Daily reconciliation: fetches last 24h of Whoop workouts to catch missed webhooks."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import async_session_factory
from app.models.connection import PlatformConnection
from app.platforms.whoop_client import (
    fetch_whoop_recovery,
    fetch_whoop_workouts,
    get_whoop_token,
    normalize_whoop_workout,
)
from app.services.workout_processor import process_workout

logger = logging.getLogger(__name__)


async def reconcile_whoop_workouts():
    """Fetch last 24h of workouts for all Whoop connections and insert any missing."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(PlatformConnection).where(
                PlatformConnection.platform == "whoop",
                PlatformConnection.is_active.is_(True),
            )
        )
        connections = result.scalars().all()

    if not connections:
        return

    logger.info("Reconciling Whoop workouts for %d connections", len(connections))

    since = datetime.now(UTC) - timedelta(hours=24)

    for conn in connections:
        async with async_session_factory() as db:
            try:
                # Re-fetch connection in this session
                result = await db.execute(
                    select(PlatformConnection).where(PlatformConnection.id == conn.id)
                )
                fresh_conn = result.scalar_one_or_none()
                if not fresh_conn or not fresh_conn.is_active:
                    continue

                token = await get_whoop_token(fresh_conn, db)

                all_workouts = await fetch_whoop_workouts(
                    token, start=since, end=datetime.now(UTC)
                )

                # Cache recovery data by date to avoid duplicate API calls
                recovery_cache: dict[str, dict | None] = {}
                count = 0
                for w in all_workouts:
                    w_start = w.get("start", "")
                    w_date = w_start[:10] if w_start else None
                    recovery_data = None
                    if w_date:
                        if w_date not in recovery_cache:
                            recovery_cache[w_date] = await fetch_whoop_recovery(token, w_date)
                        recovery_data = recovery_cache[w_date]
                    normalized = normalize_whoop_workout(w, recovery_data=recovery_data)
                    # process_workout handles deduplication via UNIQUE constraint
                    result = await process_workout(db, fresh_conn.user_id, normalized)
                    if result is not None:
                        count += 1

                if count:
                    logger.info(
                        "Reconciled %d missed Whoop workouts for user %s",
                        count,
                        fresh_conn.user_id,
                    )

            except Exception:
                logger.exception(
                    "Failed to reconcile Whoop workouts for user %s", conn.user_id
                )
