from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.connection import PlatformConnection
from app.models.user import User
from app.routers.auth import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


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
