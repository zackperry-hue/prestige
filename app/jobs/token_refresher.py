"""Proactively refreshes OAuth tokens expiring within the next 60 minutes."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import async_session_factory
from app.models.connection import PlatformConnection
from app.platforms.strava_client import refresh_strava_token
from app.platforms.wahoo_client import refresh_wahoo_token
from app.platforms.whoop_client import refresh_whoop_token

logger = logging.getLogger(__name__)

_REFRESH_FNS = {
    "strava": refresh_strava_token,
    "whoop": refresh_whoop_token,
    "wahoo": refresh_wahoo_token,
}


async def refresh_expiring_tokens():
    """Refresh all tokens expiring within the next 60 minutes."""
    threshold = datetime.now(UTC) + timedelta(minutes=60)

    async with async_session_factory() as db:
        result = await db.execute(
            select(PlatformConnection).where(
                PlatformConnection.is_active.is_(True),
                PlatformConnection.token_expires_at.isnot(None),
                PlatformConnection.token_expires_at < threshold,
                PlatformConnection.refresh_token_enc.isnot(None),
            )
        )
        connections = result.scalars().all()

        if not connections:
            return

        logger.info("Refreshing %d expiring tokens", len(connections))

        for conn in connections:
            refresh_fn = _REFRESH_FNS.get(conn.platform)
            if not refresh_fn:
                logger.warning("No refresh function for platform %s", conn.platform)
                continue

            try:
                await refresh_fn(conn, db)
                logger.info(
                    "Refreshed %s token for user %s (expires %s)",
                    conn.platform,
                    conn.user_id,
                    conn.token_expires_at,
                )
            except Exception:
                logger.exception(
                    "Failed to refresh %s token for user %s",
                    conn.platform,
                    conn.user_id,
                )
