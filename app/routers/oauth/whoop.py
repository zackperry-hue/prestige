"""Whoop OAuth2 connect + callback flow."""

import logging
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.connection import PlatformConnection
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.token_manager import encrypt_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/whoop", tags=["oauth"])

WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"


@router.get("/connect")
async def whoop_connect(token: str = Query(None), user: User = Depends(get_current_user)):
    """Redirect user to Whoop's OAuth authorization page."""
    params = {
        "client_id": settings.whoop_client_id,
        "redirect_uri": settings.whoop_redirect_uri,
        "response_type": "code",
        "scope": "read:workout read:cycles read:profile offline",
        "state": str(user.id),
    }
    return RedirectResponse(url=f"{WHOOP_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def whoop_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Exchange authorization code for access + refresh tokens."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            WHOOP_TOKEN_URL,
            data={
                "client_id": settings.whoop_client_id,
                "client_secret": settings.whoop_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.whoop_redirect_uri,
            },
        )

    if resp.status_code != 200:
        logger.error("Whoop token exchange failed: %s", resp.text)
        raise HTTPException(status_code=400, detail="Failed to connect Whoop")

    data = resp.json()
    access_token = data["access_token"]
    refresh_token = data.get("refresh_token", "")
    expires_in = data.get("expires_in", 3600)

    from datetime import UTC, datetime, timedelta

    token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    user_id = state

    # Fetch user profile to get Whoop user ID
    whoop_user_id = ""
    async with httpx.AsyncClient() as client:
        profile_resp = await client.get(
            "https://api.prod.whoop.com/developer/v1/user/profile/basic",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if profile_resp.status_code == 200:
            whoop_user_id = str(profile_resp.json().get("user_id", ""))

    # Upsert connection
    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user_id,
            PlatformConnection.platform == "whoop",
        )
    )
    conn = result.scalar_one_or_none()

    if conn:
        conn.access_token_enc = encrypt_token(access_token)
        conn.refresh_token_enc = encrypt_token(refresh_token) if refresh_token else None
        conn.token_expires_at = token_expires_at
        conn.platform_user_id = whoop_user_id
        conn.is_active = True
    else:
        conn = PlatformConnection(
            user_id=user_id,
            platform="whoop",
            platform_user_id=whoop_user_id,
            access_token_enc=encrypt_token(access_token),
            refresh_token_enc=encrypt_token(refresh_token) if refresh_token else None,
            token_expires_at=token_expires_at,
            scopes="read:workout,read:cycles,read:profile,offline",
            is_active=True,
        )
        db.add(conn)

    await db.commit()
    return RedirectResponse(url="/dashboard/ui", status_code=302)
