"""Strava webhook receiver.

GET  /webhooks/strava — subscription validation (echoes hub.challenge)
POST /webhooks/strava — activity event handler
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.webhook_event import WebhookEvent
from app.platforms.strava_client import (
    fetch_strava_activity,
    fetch_strava_activity_zones,
    get_connection_by_athlete_id,
    get_strava_token,
    normalize_strava_activity,
)
from app.services.webhook_validator import validate_strava_verify_token, validate_strava_webhook_payload
from app.services.workout_processor import process_workout

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/strava")
async def strava_subscription_validation(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    """Strava sends a GET to validate the webhook subscription.
    We must echo back the hub.challenge value.
    """
    if hub_mode != "subscribe" or not validate_strava_verify_token(hub_verify_token):
        return Response(status_code=403)

    return {"hub.challenge": hub_challenge}


@router.post("/strava")
async def strava_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Receive Strava activity events. Return 200 immediately, process in background."""
    body = await request.body()

    # Validate payload structure to reject forged/garbage requests
    if not validate_strava_webhook_payload(body):
        logger.warning("Rejected invalid Strava webhook payload")
        return Response(status_code=400)

    payload = await request.json()

    # Log the webhook event
    event = WebhookEvent(
        platform="strava",
        event_type=f"{payload.get('object_type')}:{payload.get('aspect_type')}",
        payload=payload,
    )
    db.add(event)
    await db.commit()

    object_type = payload.get("object_type")
    aspect_type = payload.get("aspect_type")

    # Only process new activity creation
    if object_type == "activity" and aspect_type == "create":
        activity_id = payload.get("object_id")
        owner_id = str(payload.get("owner_id"))
        background_tasks.add_task(
            _process_strava_activity, activity_id, owner_id, event.id
        )

    # NOTE: Strava does not HMAC-sign webhook events, so the payload is
    # effectively unauthenticated. We intentionally do NOT trust a
    # deauthorization event from the webhook body — otherwise a forged POST
    # with a known athlete_id could DoS a user's Strava integration.
    # Real deauthorizations are detected when the next token refresh fails
    # (strava_client.refresh_strava_token sets is_active=False on 4xx).
    if aspect_type == "update" and payload.get("updates", {}).get("authorized") == "false":
        owner_id = str(payload.get("owner_id"))
        logger.info(
            "Received Strava deauthorization event for athlete %s "
            "(ignored — deactivation happens on next refresh failure)",
            owner_id,
        )

    return Response(status_code=200)


async def _process_strava_activity(activity_id: int, owner_id: str, event_id):
    """Background task: fetch activity, normalize, save, email."""
    from app.database import async_session_factory

    async with async_session_factory() as db:
        try:
            conn = await get_connection_by_athlete_id(owner_id, db)
            if not conn:
                logger.warning("No active Strava connection for athlete %s", owner_id)
                return

            token = await get_strava_token(conn, db)
            activity_data = await fetch_strava_activity(activity_id, token)
            zones = await fetch_strava_activity_zones(activity_id, token)
            normalized = normalize_strava_activity(activity_data, zones=zones)
            await process_workout(db, conn.user_id, normalized)

            # Mark webhook event as processed
            from sqlalchemy import update

            from app.models.webhook_event import WebhookEvent as WE

            await db.execute(update(WE).where(WE.id == event_id).values(processed=True))
            await db.commit()

        except Exception:
            logger.exception("Failed to process Strava activity %s", activity_id)
            from sqlalchemy import update

            from app.models.webhook_event import WebhookEvent as WE

            await db.execute(
                update(WE)
                .where(WE.id == event_id)
                .values(error_message=f"Failed to process activity {activity_id}")
            )
            await db.commit()
