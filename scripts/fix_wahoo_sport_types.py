"""One-time script to re-classify existing Wahoo workouts using correct sport type mapping.

Usage:
    DATABASE_URL=your_url python scripts/fix_wahoo_sport_types.py

Or from project root with .env loaded:
    .venv/bin/python scripts/fix_wahoo_sport_types.py
"""

import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.workout import Workout
from app.models.workout_session import WorkoutSession
from app.platforms.sport_type_map import normalize_sport_type


async def fix_wahoo_sport_types():
    engine = create_async_engine(
        settings.database_url,
        connect_args={"statement_cache_size": 0},
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Get all Wahoo workouts
        result = await db.execute(
            select(Workout).where(Workout.platform == "wahoo")
        )
        wahoo_workouts = result.scalars().all()

        fixed = 0
        for w in wahoo_workouts:
            raw = w.raw_data or {}
            workout_type_id = raw.get("workout_type_id", 47)  # default to "Other"
            correct_sport = normalize_sport_type("wahoo", workout_type_id)

            if w.sport_type != correct_sport:
                old = w.sport_type
                w.sport_type = correct_sport
                fixed += 1
                print(f"  Workout {w.id}: {old} -> {correct_sport} (type_id={workout_type_id})")

        if fixed:
            await db.commit()
            print(f"\nFixed {fixed} Wahoo workouts out of {len(wahoo_workouts)} total.")
        else:
            print(f"All {len(wahoo_workouts)} Wahoo workouts already have correct sport types.")

        # Now update sessions that contain Wahoo workouts — re-derive sport_type
        # from the best workout in each session
        result = await db.execute(
            select(WorkoutSession).where(WorkoutSession.platforms.contains("wahoo"))
        )
        sessions = result.scalars().all()

        session_fixed = 0
        for s in sessions:
            # Get all workouts in this session
            result = await db.execute(
                select(Workout).where(Workout.session_id == s.id)
            )
            session_workouts = result.scalars().all()

            # Pick best sport type: prefer non-"other" types
            best_sport = "other"
            for sw in session_workouts:
                if sw.sport_type and sw.sport_type != "other":
                    best_sport = sw.sport_type
                    break

            if s.sport_type != best_sport:
                old = s.sport_type
                s.sport_type = best_sport
                session_fixed += 1
                print(f"  Session {s.id}: {old} -> {best_sport}")

        if session_fixed:
            await db.commit()
            print(f"\nFixed {session_fixed} sessions.")
        else:
            print(f"All {len(sessions)} Wahoo-related sessions already correct.")

    await engine.dispose()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(fix_wahoo_sport_types())
