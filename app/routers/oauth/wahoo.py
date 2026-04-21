"""Wahoo OAuth2 connect + callback flow."""

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

router = APIRouter(prefix="/auth/wahoo", tags=["oauth"])

WAHOO_AUTH_URL = "https://api.wahooligan.com/oauth/authorize"
WAHOO_TOKEN_URL = "https://api.wahooligan.com/oauth/token"


@router.get("/connect")
async def wahoo_connect(user: User = Depends(get_current_user)):
    """Redirect user to Wahoo's OAuth authorization page."""
    params = {
        "client_id": settings.wahoo_client_id,
        "redirect_uri": settings.wahoo_redirect_uri,
        "response_type": "code",
        "scope": "user_read workouts_read",
        "state": generate_oauth_state(str(user.id)),
    }
    return RedirectResponse(url=f"{WAHOO_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def wahoo_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Exchange authorization code for access + refresh tokens."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            WAHOO_TOKEN_URL,
            data={
                "client_id": settings.wahoo_client_id,
                "client_secret": settings.wahoo_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.wahoo_redirect_uri,
            },
        )

    if resp.status_code != 200:
        logger.error("Wahoo token exchange failed: %s", resp.text)
        # TEMP DEBUG — revert once we've identified the Wahoo OAuth failure.
        raise HTTPException(
            status_code=400,
            detail=f"Failed to connect Wahoo (status {resp.status_code}): {resp.text[:300]}",
        )

    data = resp.json()
    access_token = data["access_token"]
    refresh_token = data.get("refresh_token", "")
    expires_in = data.get("expires_in", 7200)

    from datetime import UTC, datetime, timedelta

    token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    user_id = validate_oauth_state(state)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    # Verify the authenticated user matches the state token
    current_user = await _get_user_from_cookie(request, db)
    if not current_user or str(current_user.id) != user_id:
        raise HTTPException(status_code=403, detail="OAuth session mismatch")

    # Fetch Wahoo user profile
    wahoo_user_id = ""
    async with httpx.AsyncClient(timeout=15.0) as client:
        profile_resp = await client.get(
            "https://api.wahooligan.com/v1/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if profile_resp.status_code == 200:
            wahoo_user_id = str(profile_resp.json().get("id", ""))

    # Upsert connection
    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user_id,
            PlatformConnection.platform == "wahoo",
        )
    )
    conn = result.scalar_one_or_none()

    if conn:
        conn.access_token_enc = encrypt_token(access_token)
        conn.refresh_token_enc = encrypt_token(refresh_token) if refresh_token else None
        conn.token_expires_at = token_expires_at
        conn.platform_user_id = wahoo_user_id
        conn.is_active = True
    else:
        conn = PlatformConnection(
            user_id=user_id,
            platform="wahoo",
            platform_user_id=wahoo_user_id,
            access_token_enc=encrypt_token(access_token),
            refresh_token_enc=encrypt_token(refresh_token) if refresh_token else None,
            token_expires_at=token_expires_at,
            scopes="user_read,workouts_read",
            is_active=True,
        )
        db.add(conn)

    await db.commit()
    return RedirectResponse(url="/dashboard/ui", status_code=302)
