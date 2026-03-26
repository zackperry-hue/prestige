"""Background job: send emails for sessions whose delay has elapsed.

Runs every 2 minutes. Picks up sessions where:
- email_scheduled_at has passed (10 min after first workout arrived)
- email_sent_at is still NULL

Sends one unified email per session combining data from all platforms.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import async_session_factory
from app.models.user import User
from app.models.workout_session import WorkoutSession
from app.schemas.workout import NormalizedWorkout
from app.services.email_service import send_session_email
from app.services.session_manager import get_session_workouts, get_sessions_ready_to_email
from app.services.workout_insights import generate_session_highlights

logger = logging.getLogger(__name__)


async def check_and_send_session_emails():
    """Check for sessions ready to email and send them."""
    async with async_session_factory() as db:
        try:
            sessions = await get_sessions_ready_to_email(db)
            if not sessions:
                return

            logger.info("Found %d sessions ready to email", len(sessions))

            for session in sessions:
                try:
                    # Fetch user
                    result = await db.execute(
                        select(User).where(User.id == session.user_id)
                    )
                    user = result.scalar_one_or_none()
                    if not user or not user.email_enabled:
                        session.email_sent_at = datetime.now(UTC)
                        await db.commit()
                        continue

                    # Get all workouts in this session
                    workouts = await get_session_workouts(db, session.id)

                    # Generate highlights using session data
                    highlights = await generate_session_highlights(db, user.id, session)

                    # Send unified email
                    success = await send_session_email(db, user, session, workouts, highlights)

                    if success:
                        session.email_sent_at = datetime.now(UTC)
                        await db.commit()
                        logger.info(
                            "Sent session email for %s (platforms: %s)",
                            session.id,
                            session.platforms,
                        )

                except Exception:
                    logger.exception("Failed to send email for session %s", session.id)

        except Exception:
            logger.exception("Error in session emailer job")
