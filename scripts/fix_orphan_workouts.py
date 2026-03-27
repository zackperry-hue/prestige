"""Fix orphan workouts by linking them to matching sessions."""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.workout import Workout
from app.models.workout_session import WorkoutSession

WINDOW = timedelta(minutes=15)


async def fix_orphans():
    engine = create_async_engine(
        settings.database_url,
        connect_args={"statement_cache_size": 0},
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Get orphan workouts
        result = await db.execute(
            select(Workout).where(Workout.session_id.is_(None))
        )
        orphans = result.scalars().all()

        fixed = 0
        for w in orphans:
            # Find a session that matches this workout's time window
            result = await db.execute(
                select(WorkoutSession).where(
                    WorkoutSession.user_id == w.user_id,
                    WorkoutSession.started_at >= w.started_at - WINDOW,
                    WorkoutSession.started_at <= w.started_at + WINDOW,
                )
            )
            session = result.scalar_one_or_none()

            if session:
                w.session_id = session.id

                # Add platform to session
                platforms = set(p.strip() for p in (session.platforms or "").split(",") if p.strip())
                platforms.add(w.platform)
                session.platforms = ",".join(sorted(platforms))

                # Update session with better data if available
                if w.platform == "strava":
                    if w.distance_meters:
                        session.distance_meters = w.distance_meters
                    if w.elevation_gain:
                        session.elevation_gain = w.elevation_gain
                    if w.sport_type:
                        session.sport_type = w.sport_type

                print(f"  Linked {w.platform} workout {w.id} -> session {session.id} (platforms: {session.platforms})")
                fixed += 1

        if fixed:
            await db.commit()
            print(f"\nFixed {fixed} orphan workouts.")
        else:
            print("No orphan workouts to fix.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(fix_orphans())
