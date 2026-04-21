"""UI router: serves HTML pages with cookie-based session auth."""

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytz

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.rate_limit import limiter
from app.models.connection import PlatformConnection
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.models.user_profile import UserProfile
from app.models.workout import Workout
from app.models.workout_session import WorkoutSession
from app.routers.auth import create_access_token
from app.services.password import hash_password, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"])

_base_templates = Jinja2Templates(directory="app/templates")


class _CSRFTemplates:
    """Wrapper around Jinja2Templates that auto-injects csrf_token into context."""

    def __init__(self, jinja_templates: Jinja2Templates):
        self._templates = jinja_templates

    def TemplateResponse(self, name_or_request=None, context_or_name=None, *, request: Request | None = None, name: str | None = None, context: dict | None = None, **kwargs):
        # Support both calling conventions:
        #   TemplateResponse(request=request, name="x.html", context={...})
        #   TemplateResponse("x.html", {"request": request, ...})
        if isinstance(name_or_request, str) and isinstance(context_or_name, dict):
            # Old-style: TemplateResponse("template.html", {"request": req, ...})
            name = name_or_request
            context = context_or_name
            request = context.get("request")
        elif name_or_request is None:
            # Keyword-only style
            pass

        ctx = context or {}
        if request:
            # Prefer the middleware-set token (which matches the cookie that
            # will be sent on this response) over the incoming cookie value.
            ctx["csrf_token"] = (
                getattr(request.state, "csrf_token", None)
                or request.cookies.get("csrf_token", "")
            )
        return self._templates.TemplateResponse(request=request, name=name, context=ctx, **kwargs)

    def __getattr__(self, name):
        return getattr(self._templates, name)


templates = _CSRFTemplates(_base_templates)

SPORT_ICONS = {
    "cycling": "\U0001F6B4",
    "ride": "\U0001F6B4",
    "virtualride": "\U0001F6B4",
    "running": "\U0001F3C3",
    "run": "\U0001F3C3",
    "virtualrun": "\U0001F3C3",
    "swimming": "\U0001F3CA",
    "swim": "\U0001F3CA",
    "strength": "\U0001F4AA",
    "strength training": "\U0001F4AA",
    "weighttraining": "\U0001F4AA",
}
DEFAULT_SPORT_ICON = "\U0001F6B4"


def _sport_icon(sport_type: str | None) -> str:
    if not sport_type:
        return DEFAULT_SPORT_ICON
    return SPORT_ICONS.get(sport_type.lower(), DEFAULT_SPORT_ICON)


def _distance_display(distance_meters: float | None, unit_system: str) -> str | None:
    if distance_meters is None:
        return None
    if unit_system == "metric":
        km = distance_meters / 1000
        return f"{km:.1f} km"
    else:
        miles = distance_meters / 1609.344
        return f"{miles:.1f} mi"


def _elevation_display(elevation_meters: float | None, unit_system: str) -> str | None:
    if elevation_meters is None:
        return None
    if unit_system == "metric":
        return f"{elevation_meters:.0f} m"
    else:
        feet = elevation_meters * 3.28084
        return f"{feet:.0f} ft"


async def _get_user_from_cookie(request: Request, db: AsyncSession) -> User | None:
    """Extract user from the session cookie JWT token."""
    token = request.cookies.get("session_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Login / Register / Logout
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Show login page, or redirect to dashboard if already authenticated."""
    user = await _get_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/dashboard/ui", status_code=302)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None, "success": None, "mode": "login"})


@router.post("/dashboard/ui/login", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def do_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "Invalid email or password.", "success": None, "mode": "login"},
            status_code=401,
        )

    token = create_access_token(user.id)
    response = RedirectResponse(url="/dashboard/ui", status_code=302)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
    )
    return response


@router.post("/dashboard/ui/register", response_class=HTMLResponse)
@limiter.limit("3/minute")
async def do_register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(None),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "That email is already registered.", "success": None, "mode": "register"},
            status_code=409,
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "Password must be at least 8 characters.", "success": None, "mode": "register"},
            status_code=400,
        )

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name or None,
    )
    db.add(user)
    await db.commit()

    token = create_access_token(user.id)
    response = RedirectResponse(url="/dashboard/ui/onboarding", status_code=302)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
    )
    return response


@router.get("/dashboard/ui/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("session_token")
    return response


# ---------------------------------------------------------------------------
# Forgot / Reset Password
# ---------------------------------------------------------------------------

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(request=request, name="forgot_password.html", context={
        "user": None, "message": None, "error": None,
    })


@router.post("/forgot-password", response_class=HTMLResponse)
@limiter.limit("3/minute")
async def do_forgot_password(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Always show the same message to prevent email enumeration
    success_msg = "If an account exists with that email, we've sent a password reset link."

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user:
        # Invalidate any existing tokens for this user
        existing = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        )
        for tok in existing.scalars().all():
            tok.used_at = datetime.now(timezone.utc)

        # Create new token
        token = secrets.token_urlsafe(32)
        reset_token = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(reset_token)
        await db.commit()

        # Send email
        reset_url = f"{settings.app_base_url}/reset-password?token={token}"
        from app.services.email_service import send_password_reset_email
        send_password_reset_email(user.email, reset_url)

    return templates.TemplateResponse(request=request, name="forgot_password.html", context={
        "user": None, "message": success_msg, "error": None,
    })


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    if not token:
        return templates.TemplateResponse(request=request, name="reset_password.html", context={
            "user": None, "token": "", "error": "Invalid or missing reset link.",
        })

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == token,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > datetime.now(timezone.utc),
        )
    )
    reset_token = result.scalar_one_or_none()

    if not reset_token:
        return templates.TemplateResponse(request=request, name="reset_password.html", context={
            "user": None, "token": "", "error": "This reset link is invalid or has expired. Please request a new one.",
        })

    return templates.TemplateResponse(request=request, name="reset_password.html", context={
        "user": None, "token": token, "error": None,
    })


@router.post("/reset-password", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def do_reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == token,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > datetime.now(timezone.utc),
        )
    )
    reset_token = result.scalar_one_or_none()

    if not reset_token:
        return templates.TemplateResponse(request=request, name="reset_password.html", context={
            "user": None, "token": "", "error": "This reset link is invalid or has expired. Please request a new one.",
        })

    if len(password) < 8:
        return templates.TemplateResponse(request=request, name="reset_password.html", context={
            "user": None, "token": token, "error": "Password must be at least 8 characters.",
        })

    # Update the user's password
    user_result = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return templates.TemplateResponse(request=request, name="reset_password.html", context={
            "user": None, "token": "", "error": "Account not found.",
        })

    user.password_hash = hash_password(password)
    reset_token.used_at = datetime.now(timezone.utc)
    await db.commit()

    # Redirect to login with success message
    return templates.TemplateResponse(request=request, name="login.html", context={
        "error": None, "success": "Password reset successfully. Sign in with your new password.", "mode": "login",
    })


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/dashboard/ui", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)

    # Eagerly load the user profile for the dashboard template
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    user.profile = result.scalar_one_or_none()

    # Get connected platforms
    result = await db.execute(
        select(PlatformConnection)
        .where(PlatformConnection.user_id == user.id)
        .where(PlatformConnection.is_active.is_(True))
    )
    connections = result.scalars().all()
    connected_platforms = {c.platform for c in connections}

    # Get recent sessions (grouped workouts) — last 10
    result = await db.execute(
        select(WorkoutSession)
        .where(WorkoutSession.user_id == user.id)
        .order_by(WorkoutSession.started_at.desc())
        .limit(10)
    )
    sessions = result.scalars().all()

    # Also get recent workouts that have NO session (orphans)
    result = await db.execute(
        select(Workout)
        .where(Workout.user_id == user.id, Workout.session_id.is_(None))
        .order_by(Workout.started_at.desc())
        .limit(10)
    )
    orphan_workouts = result.scalars().all()

    # Build a unified workout list from sessions + orphans
    workout_list = []
    for s in sessions:
        s.sport_icon = _sport_icon(s.sport_type)
        s.distance_display = _distance_display(s.distance_meters, user.unit_system)
        s.platform_list = [p.strip() for p in (s.platforms or "").split(",") if p.strip()]
        s.is_session = True
        workout_list.append(s)

    for w in orphan_workouts:
        w.sport_icon = _sport_icon(w.sport_type)
        w.distance_display = _distance_display(w.distance_meters, user.unit_system)
        w.platform_list = [w.platform]
        w.is_session = False
        workout_list.append(w)

    # Sort combined list by started_at descending, take top 10
    workout_list.sort(key=lambda x: x.started_at, reverse=True)
    workout_list = workout_list[:10]

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "user": user,
        "connected_platforms": connected_platforms,
        "workouts": workout_list,
    })


# ---------------------------------------------------------------------------
# HTMX: Disconnect platform
# ---------------------------------------------------------------------------

@router.post("/dashboard/ui/disconnect/{platform}", response_class=HTMLResponse)
async def disconnect_platform(platform: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if platform not in ("strava", "whoop", "wahoo", "garmin"):
        raise HTTPException(status_code=400, detail="Invalid platform")

    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user.id,
            PlatformConnection.platform == platform,
            PlatformConnection.is_active.is_(True),
        )
    )
    conn = result.scalar_one_or_none()
    if conn:
        conn.is_active = False
        await db.commit()

    # Platform display config
    config = {
        "strava": {"name": "Strava", "brand_color": "#FC4C02"},
        "whoop": {"name": "Whoop", "brand_color": "#00B8B0"},
        "wahoo": {"name": "Wahoo", "brand_color": "#0068FF"},
    }
    p = config[platform]

    # Return the disconnected-state HTML fragment for HTMX swap
    return HTMLResponse(f"""
    <div id="platform-{platform}" class="flex items-center justify-between py-3">
        <div class="flex items-center space-x-3">
            <span class="w-1 h-8 rounded-full" style="background-color: {p['brand_color']};"></span>
            <span class="font-medium text-white text-sm">{p['name']}</span>
        </div>
        <div class="flex items-center space-x-1.5">
            <span class="w-2 h-2 rounded-full bg-gray-600"></span>
            <span class="text-xs text-gray-500">Not Connected</span>
        </div>
        <div>
            <a href="/auth/{platform}/connect"
               class="px-3 py-1.5 rounded-lg text-xs font-medium text-white transition-colors inline-block"
               style="background-color: {p['brand_color']}; opacity: 0.9;"
               onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.9'">
                Connect
            </a>
        </div>
    </div>
    """)


# ---------------------------------------------------------------------------
# HTMX: Save preferences
# ---------------------------------------------------------------------------

@router.patch("/dashboard/ui/preferences", response_class=HTMLResponse)
async def save_preferences(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    form = await request.form()
    unit_system = form.get("unit_system")
    timezone = form.get("timezone")
    email_enabled = form.get("email_enabled")

    if unit_system and unit_system in ("metric", "imperial"):
        user.unit_system = unit_system
    if timezone:
        if timezone not in pytz.all_timezones:
            raise HTTPException(status_code=400, detail="Invalid timezone")
        user.timezone = timezone
    user.email_enabled = email_enabled == "true"

    await db.commit()

    return HTMLResponse(
        '<span class="text-green-400">Preferences saved!</span>'
    )


# ---------------------------------------------------------------------------
# Onboarding / Edit Profile
# ---------------------------------------------------------------------------

@router.get("/dashboard/ui/onboarding", response_class=HTMLResponse)
async def onboarding_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)

    # Check if profile exists already (edit mode)
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    profile = result.scalar_one_or_none()

    return templates.TemplateResponse(request=request, name="onboarding.html", context={
        "user": user,
        "profile": profile,
        "is_edit": profile is not None,
    })


@router.post("/dashboard/ui/onboarding", response_class=HTMLResponse)
async def save_onboarding(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)

    form = await request.form()

    # Multi-select fields come as lists
    fitness_goals = ",".join(form.getlist("fitness_goals"))
    primary_sports = ",".join(form.getlist("primary_sports"))
    experience_level = form.get("experience_level") or None
    weekly_target_str = form.get("weekly_target")
    weekly_target = None
    if weekly_target_str:
        try:
            weekly_target = int(weekly_target_str)
            if weekly_target < 0 or weekly_target > 50:
                weekly_target = None
        except ValueError:
            weekly_target = None
    target_event_name = form.get("target_event_name") or None
    target_event_date = form.get("target_event_date") or None
    additional_context = form.get("additional_context") or None

    # Upsert profile
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    profile = result.scalar_one_or_none()

    if profile:
        profile.fitness_goals = fitness_goals or None
        profile.experience_level = experience_level
        profile.primary_sports = primary_sports or None
        profile.weekly_target = weekly_target
        profile.target_event_name = target_event_name
        profile.target_event_date = target_event_date
        profile.additional_context = additional_context
    else:
        profile = UserProfile(
            user_id=user.id,
            fitness_goals=fitness_goals or None,
            experience_level=experience_level,
            primary_sports=primary_sports or None,
            weekly_target=weekly_target,
            target_event_name=target_event_name,
            target_event_date=target_event_date,
            additional_context=additional_context,
        )
        db.add(profile)

    await db.commit()
    return RedirectResponse(url="/dashboard/ui", status_code=302)


# ---------------------------------------------------------------------------
# Workout Detail
# ---------------------------------------------------------------------------

@router.get("/dashboard/ui/session/{session_id}", response_class=HTMLResponse)
async def session_detail_page(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Show detail page for a merged workout session."""
    user = await _get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)

    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await db.execute(
        select(WorkoutSession).where(WorkoutSession.id == sid, WorkoutSession.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Load all workouts in this session
    result = await db.execute(
        select(Workout).where(Workout.session_id == sid, Workout.user_id == user.id).order_by(Workout.platform)
    )
    session_workouts = result.scalars().all()

    return templates.TemplateResponse(request=request, name="workout_detail.html", context={
        "user": user,
        "workout": session_workouts[0] if session_workouts else None,
        "session": session,
        "session_workouts": session_workouts,
        "sport_icon": _sport_icon(session.sport_type),
        "distance_display": _distance_display(session.distance_meters, user.unit_system),
        "elevation_display": _elevation_display(session.elevation_gain, user.unit_system),
        "session_distance_display": _distance_display(session.distance_meters, user.unit_system),
        "session_elevation_display": _elevation_display(session.elevation_gain, user.unit_system),
    })


@router.get("/dashboard/ui/workout/{workout_id}", response_class=HTMLResponse)
async def workout_detail_page(workout_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/", status_code=302)

    try:
        wid = uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Workout not found")

    result = await db.execute(
        select(Workout).where(Workout.id == wid, Workout.user_id == user.id)
    )
    workout = result.scalar_one_or_none()
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    # Load session if linked
    session = None
    session_distance_display = None
    session_elevation_display = None
    if workout.session_id:
        result = await db.execute(
            select(WorkoutSession).where(WorkoutSession.id == workout.session_id, WorkoutSession.user_id == user.id)
        )
        session = result.scalar_one_or_none()
        if session:
            session_distance_display = _distance_display(session.distance_meters, user.unit_system)
            session_elevation_display = _elevation_display(session.elevation_gain, user.unit_system)

    return templates.TemplateResponse(request=request, name="workout_detail.html", context={
        "user": user,
        "workout": workout,
        "session": session,
        "sport_icon": _sport_icon(workout.sport_type),
        "distance_display": _distance_display(workout.distance_meters, user.unit_system),
        "elevation_display": _elevation_display(workout.elevation_gain, user.unit_system),
        "session_distance_display": session_distance_display,
        "session_elevation_display": session_elevation_display,
    })
