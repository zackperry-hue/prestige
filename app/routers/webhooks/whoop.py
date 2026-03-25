"""Whoop webhook receiver.

POST /webhooks/whoop — workout event handler with HMAC-SHA256 validation
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.webhook_event import WebhookEvent
from app.platforms.whoop_client import (
    fetch_whoop_workout,
    get_connection_by_whoop_user,
    get_whoop_token,
    normalize_whoop_workout,
)
from app.services.webhook_validator import validate_whoop_signature
from app.services.workout_processor import process_workout

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/whoop")
async def whoop_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_whoop_signature: str = Header("", alias="x-whoop-signature"),
    x_whoop_signature_timestamp: str = Header("", alias="x-whoop-signature-timestamp"),
):
    """Receive Whoop webhook events. Validate HMAC, return 200, process in background."""
    body = await request.body()

    # Validate signature
    if x_whoop_signature and not validate_whoop_signature(
        body, x_whoop_signature_timestamp, x_whoop_signature
    ):
        logger.warning("Invalid Whoop webhook signature")
        return Response(status_code=401)

    payload = await request.json()

    # Log the webhook event
    event_type = payload.get("type", "unknown")
    event = WebhookEvent(
        platform="whoop",
        event_type=event_type,
        payload=payload,
    )
    db.add(event)
    await db.commit()

    # Process workout events
    if "workout" in event_type.lower():
        user_id = str(payload.get("user_id", ""))
        workout_id = str(payload.get("id", payload.get("workout_id", "")))

        if user_id and workout_id:
            background_tasks.add_task(
                _process_whoop_workout, user_id, workout_id, event.id
            )

    return Response(status_code=200)


async def _process_whoop_workout(whoop_user_id: str, workout_id: str, event_id):
    """Background task: fetch workout, normalize, save, email."""
    from app.database import async_session_factory

    async with async_session_factory() as db:
        try:
            conn = await get_connection_by_whoop_user(whoop_user_id, db)
            if not conn:
                logger.warning("No active Whoop connection for user %s", whoop_user_id)
                return

            token = await get_whoop_token(conn, db)
            workout_data = await fetch_whoop_workout(workout_id, token)
            normalized = normalize_whoop_workout(workout_data)
            await process_workout(db, conn.user_id, normalized)

            # Mark webhook event as processed
            from sqlalchemy import update

            from app.models.webhook_event import WebhookEvent as WE

            await db.execute(update(WE).where(WE.id == event_id).values(processed=True))
            await db.commit()

        except Exception:
            logger.exception("Failed to process Whoop workout %s", workout_id)
            from sqlalchemy import update

            from app.models.webhook_event import WebhookEvent as WE

            await db.execute(
                update(WE)
                .where(WE.id == event_id)
                .values(error_message=f"Failed to process workout {workout_id}")
            )
            await db.commit()
