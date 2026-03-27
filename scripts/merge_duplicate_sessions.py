"""One-time script to merge duplicate sessions that should have been combined.

Finds sessions for the same user within a ±15 min time window and merges them.

Usage:
    .venv/bin/python scripts/merge_duplicate_sessions.py
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.workout import Workout
from app.models.workout_session import WorkoutSession
from app.services.session_manager import merge_into_session
from app.schemas.workout import NormalizedWorkout

WINDOW = timedelta(minutes=15)


async def merge_duplicate_sessions():
    engine = create_async_engine(
        settings.database_url,
        connect_args={"statement_cache_size": 0},
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Get all sessions ordered by user and start time
        result = await db.execute(
            select(WorkoutSession).order_by(
                WorkoutSession.user_id, WorkoutSession.started_at
            )
        )
        all_sessions = result.scalars().all()

        merged_count = 0
        deleted_ids = set()

        for i, s1 in enumerate(all_sessions):
            if s1.id in deleted_ids:
                continue

            for j in range(i + 1, len(all_sessions)):
                s2 = all_sessions[j]
                if s2.id in deleted_ids:
                    continue

                # Must be same user
                if s2.user_id != s1.user_id:
                    break

                # Check time overlap (±15 min window)
                if abs((s2.started_at - s1.started_at).total_seconds()) > WINDOW.total_seconds():
                    # If s2 is too far ahead, no more matches for s1
                    if s2.started_at > s1.started_at + WINDOW:
                        break
                    continue

                # Found a duplicate — merge s2 into s1
                print(f"  Merging session {s2.id} into {s1.id}")
                print(f"    s1: {s1.started_at} platforms={s1.platforms} sport={s1.sport_type}")
                print(f"    s2: {s2.started_at} platforms={s2.platforms} sport={s2.sport_type}")

                # Merge fields: take best values
                if s2.started_at < s1.started_at:
                    s1.started_at = s2.started_at
                if s2.ended_at and (s1.ended_at is None or s2.ended_at > s1.ended_at):
                    s1.ended_at = s2.ended_at
                if s2.duration_seconds and (s1.duration_seconds is None or s2.duration_seconds > s1.duration_seconds):
                    s1.duration_seconds = s2.duration_seconds
                # Distance: prefer strava
                if s2.distance_meters:
                    s2_platforms = set((s2.platforms or "").split(","))
                    if "strava" in s2_platforms or s1.distance_meters is None:
                        s1.distance_meters = s2.distance_meters
                if s2.calories and (s1.calories is None or s2.calories > s1.calories):
                    s1.calories = s2.calories
                # Heart rate: prefer whoop
                if s2.avg_heart_rate:
                    s2_platforms = set((s2.platforms or "").split(","))
                    if "whoop" in s2_platforms or s1.avg_heart_rate is None:
                        s1.avg_heart_rate = s2.avg_heart_rate
                        s1.max_heart_rate = s2.max_heart_rate or s1.max_heart_rate
                if s2.elevation_gain:
                    s2_platforms = set((s2.platforms or "").split(","))
                    if "strava" in s2_platforms or s1.elevation_gain is None:
                        s1.elevation_gain = s2.elevation_gain
                if s2.avg_power_watts and s1.avg_power_watts is None:
                    s1.avg_power_watts = s2.avg_power_watts
                if s2.strain_score and s1.strain_score is None:
                    s1.strain_score = s2.strain_score

                # Sport type: prefer strava, then non-"other"
                s2_platforms = set((s2.platforms or "").split(","))
                if "strava" in s2_platforms and s2.sport_type:
                    s1.sport_type = s2.sport_type
                elif s1.sport_type in (None, "other") and s2.sport_type and s2.sport_type != "other":
                    s1.sport_type = s2.sport_type

                # Merge platform lists
                p1 = set(p.strip() for p in (s1.platforms or "").split(",") if p.strip())
                p2 = set(p.strip() for p in (s2.platforms or "").split(",") if p.strip())
                s1.platforms = ",".join(sorted(p1 | p2))

                # Preserve email state (keep sent if either was sent)
                if s2.email_sent_at and not s1.email_sent_at:
                    s1.email_sent_at = s2.email_sent_at

                # Move all workouts from s2 to s1
                await db.execute(
                    update(Workout)
                    .where(Workout.session_id == s2.id)
                    .values(session_id=s1.id)
                )

                # Delete s2
                await db.execute(
                    delete(WorkoutSession).where(WorkoutSession.id == s2.id)
                )

                deleted_ids.add(s2.id)
                merged_count += 1
                print(f"    -> merged! platforms now: {s1.platforms}")

        if merged_count:
            await db.commit()
            print(f"\nMerged {merged_count} duplicate sessions.")
        else:
            print("No duplicate sessions found.")

    await engine.dispose()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(merge_duplicate_sessions())
