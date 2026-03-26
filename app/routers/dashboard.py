from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.connection import PlatformConnection
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.user import UserResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class PreferencesUpdate(BaseModel):
    unit_system: str | None = None  # "metric" or "imperial"
    timezone: str | None = None
    email_enabled: bool | None = None


@router.patch("/preferences", response_model=UserResponse)
async def update_preferences(
    data: PreferencesUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if data.unit_system is not None:
        if data.unit_system not in ("metric", "imperial"):
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="unit_system must be 'metric' or 'imperial'")
        user.unit_system = data.unit_system
    if data.timezone is not None:
        user.timezone = data.timezone
    if data.email_enabled is not None:
        user.email_enabled = data.email_enabled
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/connections")
async def list_connections(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PlatformConnection)
        .where(PlatformConnection.user_id == user.id)
        .where(PlatformConnection.is_active.is_(True))
    )
    connections = result.scalars().all()
    return [
        {
            "platform": c.platform,
            "platform_user_id": c.platform_user_id,
            "connected_at": c.created_at,
        }
        for c in connections
    ]
