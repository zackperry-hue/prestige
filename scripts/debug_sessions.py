"""Debug script to check session/workout state."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.workout import Workout
from app.models.workout_session import WorkoutSession


async def debug():
    engine = create_async_engine(
        settings.database_url,
        connect_args={"statement_cache_size": 0},
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Recent workouts
        result = await db.execute(
            select(Workout).order_by(Workout.started_at.desc()).limit(20)
        )
        workouts = result.scalars().all()

        print("=== RECENT WORKOUTS ===")
        for w in workouts:
            print(f"  {w.started_at} | {w.platform:8s} | {w.sport_type:10s} | session={w.session_id} | id={w.id}")

        # Recent sessions
        result = await db.execute(
            select(WorkoutSession).order_by(WorkoutSession.started_at.desc()).limit(15)
        )
        sessions = result.scalars().all()

        print("\n=== RECENT SESSIONS ===")
        for s in sessions:
            print(f"  {s.started_at} | platforms={s.platforms:20s} | sport={s.sport_type:10s} | id={s.id}")

        # Orphan workouts (no session)
        result = await db.execute(
            select(Workout).where(Workout.session_id.is_(None)).order_by(Workout.started_at.desc()).limit(10)
        )
        orphans = result.scalars().all()

        print(f"\n=== ORPHAN WORKOUTS (no session): {len(orphans)} ===")
        for w in orphans:
            print(f"  {w.started_at} | {w.platform:8s} | {w.sport_type:10s} | id={w.id}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(debug())
