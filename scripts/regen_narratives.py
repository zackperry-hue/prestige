"""Regenerate workout narratives for a user's sessions in a date range.

Dev tool for prompt tuning. Not intended for production use.

Usage:
    .venv/bin/python scripts/regen_narratives.py <email> <YYYY-MM-DD> <YYYY-MM-DD>
"""

import asyncio
import sys
from datetime import datetime, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.user import User
from app.models.user_profile import UserProfile
from app.models.workout_session import WorkoutSession
from app.services.narrative_generator import _build_workout_context, generate_workout_narrative
from app.services.workout_insights import generate_session_highlights


async def run(email: str, start_iso: str, end_iso: str):
    start = datetime.fromisoformat(start_iso).replace(tzinfo=UTC)
    end = datetime.fromisoformat(end_iso).replace(hour=23, minute=59, second=59, tzinfo=UTC)

    engine = create_async_engine(settings.database_url, connect_args={"statement_cache_size": 0})
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not user:
            print(f"No user {email}")
            return

        profile = (
            await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
        ).scalar_one_or_none()

        sessions = (
            await db.execute(
                select(WorkoutSession)
                .where(
                    WorkoutSession.user_id == user.id,
                    WorkoutSession.started_at >= start,
                    WorkoutSession.started_at <= end,
                )
                .order_by(WorkoutSession.started_at.desc())
            )
        ).scalars().all()

        print(f"Found {len(sessions)} sessions for {email}\n")
        units = getattr(user, "unit_system", "imperial")
        user_name = user.display_name or user.email.split("@")[0]

        for s in sessions:
            print("=" * 80)
            print(f"SESSION {s.started_at.date()}  {s.sport_type}  via {s.platforms}  id={s.id}")
            print("=" * 80)

            highlights = await generate_session_highlights(db, user.id, s, units=units)
            ctx = _build_workout_context(s, highlights, user_name, units=units, profile=profile)

            print("\n--- INPUT CONTEXT ---")
            print(ctx)

            print("\n--- NEW NARRATIVE ---")
            new = await generate_workout_narrative(
                s, highlights, user_name, units=units, profile=profile, db=db
            )
            print(new or "(generation failed)")
            print()

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: regen_narratives.py <email> <start YYYY-MM-DD> <end YYYY-MM-DD>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1], sys.argv[2], sys.argv[3]))
