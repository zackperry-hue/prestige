"""Garmin Connect login flow.

Uses username/password auth via python-garminconnect for testing.
Will migrate to OAuth 2.0 PKCE when official Garmin API access is approved.
"""

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from garminconnect import Garmin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.connection import PlatformConnection
from app.routers.ui import _get_user_from_cookie, templates
from app.services.token_manager import encrypt_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/garmin", tags=["oauth"])


@router.get("/connect", response_class=HTMLResponse)
async def garmin_connect_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Show Garmin credentials form."""
    user = await _get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("garmin_connect.html", {
        "request": request,
        "user": user,
        "error": None,
    })


@router.post("/connect")
async def garmin_connect(request: Request, db: AsyncSession = Depends(get_db)):
    """Authenticate with Garmin using credentials and store session."""
    user = await _get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)

    form = await request.form()
    garmin_email = form.get("garmin_email", "")
    garmin_password = form.get("garmin_password", "")

    try:
        client = Garmin(garmin_email, garmin_password)
        client.login()
    except Exception as e:
        logger.error("Garmin login failed: %s", e)
        return templates.TemplateResponse("garmin_connect.html", {
            "request": request,
            "user": user,
            "error": "Invalid Garmin credentials. Please check your email and password.",
        })

    # Store session tokens (not raw password) for future use
    token_data = {
        "garth_tokens": client.garth.dumps(),
        "display_name": client.display_name or garmin_email,
    }

    garmin_user_id = str(client.display_name or garmin_email)

    # Upsert connection
    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user.id,
            PlatformConnection.platform == "garmin",
        )
    )
    conn = result.scalar_one_or_none()

    if conn:
        conn.access_token_enc = encrypt_token(json.dumps(token_data))
        conn.platform_user_id = garmin_user_id
        conn.is_active = True
    else:
        conn = PlatformConnection(
            user_id=user.id,
            platform="garmin",
            platform_user_id=garmin_user_id,
            access_token_enc=encrypt_token(json.dumps(token_data)),
            scopes="activities,health",
            is_active=True,
        )
        db.add(conn)

    await db.commit()
    return RedirectResponse(url="/dashboard/ui", status_code=302)
