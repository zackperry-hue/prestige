"""Daily reconciliation: fetches last 24h of Whoop workouts to catch missed webhooks."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import async_session_factory
from app.models.connection import PlatformConnection
from app.platforms.whoop_client import fetch_whoop_recovery, get_whoop_token, normalize_whoop_workout
from app.services.token_manager import decrypt_token
from app.services.workout_processor import process_workout

logger = logging.getLogger(__name__)

WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2"


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

                import httpx

                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{WHOOP_API_BASE}/activity/workout",
                        headers={"Authorization": f"Bearer {token}"},
                        params={
                            "start": since.isoformat(),
                            "end": datetime.now(UTC).isoformat(),
                            "limit": 50,
                        },
                    )

                if resp.status_code != 200:
                    logger.error(
                        "Whoop reconciliation fetch failed for user %s: %s",
                        fresh_conn.user_id,
                        resp.text,
                    )
                    continue

                data = resp.json()
                workouts = data.get("records", [])

                count = 0
                for w in workouts:
                    # Fetch recovery for the workout date
                    w_start = w.get("start", "")
                    w_date = w_start[:10] if w_start else None
                    recovery_data = None
                    if w_date:
                        recovery_data = await fetch_whoop_recovery(token, w_date)
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
