"""Strava OAuth2 connect + callback flow."""

import logging
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Request

from app.config import settings
from app.database import get_db
from app.models.connection import PlatformConnection
from app.models.user import User
from app.routers.auth import get_current_user
from app.routers.ui import _get_user_from_cookie
from app.services.oauth_state import generate_oauth_state, validate_oauth_state
from app.services.token_manager import encrypt_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/strava", tags=["oauth"])

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


@router.get("/connect")
async def strava_connect(user: User = Depends(get_current_user)):
    """Redirect user to Strava's OAuth authorization page."""
    params = {
        "client_id": settings.strava_client_id,
        "redirect_uri": settings.strava_redirect_uri,
        "response_type": "code",
        "scope": "read,activity:read_all",
        "state": generate_oauth_state(str(user.id)),
        "approval_prompt": "auto",
    }
    return RedirectResponse(url=f"{STRAVA_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def strava_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Exchange authorization code for access + refresh tokens."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )

    if resp.status_code != 200:
        logger.error("Strava token exchange failed: %s", resp.text)
        raise HTTPException(status_code=400, detail="Failed to connect Strava")

    data = resp.json()
    access_token = data["access_token"]
    refresh_token = data["refresh_token"]
    expires_at = data["expires_at"]
    athlete = data.get("athlete", {})
    athlete_id = str(athlete.get("id", ""))

    from datetime import UTC, datetime

    token_expires_at = datetime.fromtimestamp(expires_at, tz=UTC)
    user_id = validate_oauth_state(state)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    # Verify the authenticated user matches the state token
    current_user = await _get_user_from_cookie(request, db)
    if not current_user or str(current_user.id) != user_id:
        raise HTTPException(status_code=403, detail="OAuth session mismatch")

    # Upsert connection
    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user_id,
            PlatformConnection.platform == "strava",
        )
    )
    conn = result.scalar_one_or_none()

    if conn:
        conn.access_token_enc = encrypt_token(access_token)
        conn.refresh_token_enc = encrypt_token(refresh_token)
        conn.token_expires_at = token_expires_at
        conn.platform_user_id = athlete_id
        conn.is_active = True
    else:
        conn = PlatformConnection(
            user_id=user_id,
            platform="strava",
            platform_user_id=athlete_id,
            access_token_enc=encrypt_token(access_token),
            refresh_token_enc=encrypt_token(refresh_token),
            token_expires_at=token_expires_at,
            scopes="read,activity:read_all",
            is_active=True,
        )
        db.add(conn)

    await db.commit()
    return RedirectResponse(url="/dashboard/ui", status_code=302)
