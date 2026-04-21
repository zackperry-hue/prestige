"""Prune old webhook_events rows so the table doesn't grow unbounded.

Runs daily. Deletes processed events older than RETENTION_DAYS and keeps
unprocessed/errored events for a longer window so we can still debug them.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.database import async_session_factory
from app.models.webhook_event import WebhookEvent

logger = logging.getLogger(__name__)

PROCESSED_RETENTION_DAYS = 30
UNPROCESSED_RETENTION_DAYS = 90


async def cleanup_webhook_events():
    """Delete old webhook_events rows. Returns (processed_deleted, unprocessed_deleted)."""
    now = datetime.now(UTC)
    processed_cutoff = now - timedelta(days=PROCESSED_RETENTION_DAYS)
    unprocessed_cutoff = now - timedelta(days=UNPROCESSED_RETENTION_DAYS)

    async with async_session_factory() as db:
        try:
            processed_result = await db.execute(
                delete(WebhookEvent).where(
                    WebhookEvent.processed.is_(True),
                    WebhookEvent.received_at < processed_cutoff,
                )
            )
            unprocessed_result = await db.execute(
                delete(WebhookEvent).where(
                    WebhookEvent.processed.is_(False),
                    WebhookEvent.received_at < unprocessed_cutoff,
                )
            )
            await db.commit()

            p = processed_result.rowcount or 0
            u = unprocessed_result.rowcount or 0
            if p or u:
                logger.info(
                    "Pruned webhook_events: %d processed (>%dd), %d unprocessed (>%dd)",
                    p, PROCESSED_RETENTION_DAYS, u, UNPROCESSED_RETENTION_DAYS,
                )
        except Exception:
            logger.exception("webhook_events cleanup failed")
