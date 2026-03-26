import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.logging_config import setup_logging

setup_logging()

from app.jobs.session_emailer import check_and_send_session_emails
from app.jobs.token_refresher import refresh_expiring_tokens
from app.jobs.wahoo_poller import poll_wahoo_workouts
from app.jobs.whoop_reconciler import reconcile_whoop_workouts
from app.routers import auth, dashboard, ui
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
    scheduler.add_job(poll_wahoo_workouts, "interval", minutes=5, id="wahoo_poller")
    scheduler.add_job(refresh_expiring_tokens, "interval", minutes=30, id="token_refresher")
    scheduler.add_job(reconcile_whoop_workouts, "cron", hour=3, minute=17, id="whoop_reconciler")
    scheduler.add_job(check_and_send_session_emails, "interval", minutes=2, id="session_emailer")
    scheduler.start()
    logger.info("Scheduler started with 4 jobs")
    yield
    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Scheduler shut down")


app = FastAPI(title="Workout Tracker", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(strava_oauth.router)
app.include_router(whoop_oauth.router)
app.include_router(wahoo_oauth.router)
app.include_router(strava_webhook.router)
app.include_router(whoop_webhook.router)
app.include_router(ui.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
