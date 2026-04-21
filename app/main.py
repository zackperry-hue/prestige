import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded

from app.rate_limit import limiter

from app.logging_config import setup_logging

setup_logging()

from app.jobs.garmin_poller import poll_garmin_activities
from app.jobs.session_emailer import check_and_send_session_emails
from app.jobs.token_refresher import refresh_expiring_tokens
from app.jobs.wahoo_poller import poll_wahoo_workouts
from app.jobs.webhook_cleanup import cleanup_webhook_events
from app.jobs.whoop_reconciler import reconcile_whoop_workouts
from app.routers import auth, dashboard, ui
from app.routers.oauth import garmin as garmin_oauth
from app.routers.oauth import strava as strava_oauth
from app.routers.oauth import wahoo as wahoo_oauth
from app.routers.oauth import whoop as whoop_oauth
from app.routers.webhooks import strava as strava_webhook
from app.routers.webhooks import whoop as whoop_webhook

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    scheduler.add_job(poll_wahoo_workouts, "interval", minutes=15, id="wahoo_poller")
    scheduler.add_job(poll_garmin_activities, "interval", minutes=5, id="garmin_poller")
    scheduler.add_job(refresh_expiring_tokens, "interval", minutes=30, id="token_refresher")
    scheduler.add_job(reconcile_whoop_workouts, "cron", hour=3, minute=17, id="whoop_reconciler")
    scheduler.add_job(check_and_send_session_emails, "interval", minutes=2, id="session_emailer")
    scheduler.add_job(cleanup_webhook_events, "cron", hour=4, minute=7, id="webhook_cleanup")
    scheduler.start()
    logger.info("Scheduler started with 6 jobs")
    yield
    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Scheduler shut down")


app = FastAPI(title="Workout Tracker", version="0.1.0", lifespan=lifespan)

# CSRF protection for all form-based endpoints
from app.middleware.csrf import CSRFMiddleware
app.add_middleware(CSRFMiddleware)

app.state.limiter = limiter
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ---------------------------------------------------------------------------
# Global error handlers — branded HTML error pages
# ---------------------------------------------------------------------------

_error_templates = Jinja2Templates(directory="app/templates")

_ERROR_MESSAGES = {
    401: ("Session Expired", "Your session has expired. Please sign in again."),
    403: ("Access Denied", "You don't have permission to access this page."),
    404: ("Page Not Found", "The page you're looking for doesn't exist or has been moved."),
    405: ("Method Not Allowed", "This action isn't supported."),
    429: ("Too Many Requests", "You're making requests too quickly. Please wait a moment and try again."),
}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Let API routes return JSON errors
    if request.url.path.startswith("/api/") or request.url.path.startswith("/webhooks/"):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    title, message = _ERROR_MESSAGES.get(exc.status_code, ("Error", str(exc.detail)))
    return _error_templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"status_code": exc.status_code, "title": title, "message": message, "user": None},
        status_code=exc.status_code,
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server error on %s", request.url.path)
    return _error_templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"status_code": 500, "title": "Something Went Wrong", "message": "An unexpected error occurred. Please try again later.", "user": None},
        status_code=500,
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return _error_templates.TemplateResponse(
        request=request,
        name="error.html",
        context={
            "status_code": 429,
            "title": "Too Many Requests",
            "message": "You're making requests too quickly. Please wait a moment and try again.",
            "user": None,
        },
        status_code=429,
    )


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(strava_oauth.router)
app.include_router(whoop_oauth.router)
app.include_router(wahoo_oauth.router)
app.include_router(garmin_oauth.router)
app.include_router(strava_webhook.router)
app.include_router(whoop_webhook.router)
app.include_router(ui.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
