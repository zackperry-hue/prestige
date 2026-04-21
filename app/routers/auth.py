import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.user import TokenResponse, UserCreate, UserLogin, UserResponse
from app.services.password import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer_scheme = HTTPBearer(auto_error=False)

# Fixed dummy bcrypt hash used to equalize login timing when the email
# doesn't exist. Prevents user enumeration via response-time differences.
_DUMMY_BCRYPT_HASH = "$2b$12$0000000000000000000000000000000000000000000000000000"


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def create_access_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> User:
    # Accept token from Authorization header or session cookie
    raw_token = None
    if credentials:
        raw_token = credentials.credentials
    else:
        raw_token = request.cookies.get("session_token")

    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(raw_token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(request: Request, data: UserCreate, db: AsyncSession = Depends(get_db)):
    email = _normalize_email(data.email)
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        # Notify the real account holder and return a generic response.
        # API clients get a 202 Accepted rather than 409 so the signal is
        # indistinguishable from a successful registration at the HTTP level.
        from app.services.email_service import send_existing_account_alert_email
        await asyncio.to_thread(send_existing_account_alert_email, email)
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail="Registration received. Check your email for next steps.",
        )

    user = User(
        email=email,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
        timezone=data.timezone,
        unit_system=data.unit_system,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, data: UserLogin, db: AsyncSession = Depends(get_db)):
    email = _normalize_email(data.email)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    # Always run bcrypt so timing doesn't leak whether the email exists.
    password_hash = user.password_hash if user else _DUMMY_BCRYPT_HASH
    password_ok = verify_password(data.password, password_hash)
    if not user or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user
