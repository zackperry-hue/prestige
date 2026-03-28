import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class NormalizedWorkout(BaseModel):
    platform: Literal["whoop", "strava", "wahoo", "garmin"]
    platform_workout_id: str
    sport_type: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int
    distance_meters: float | None = None
    calories: float | None = None
    avg_heart_rate: float | None = None
    max_heart_rate: float | None = None
    strain_score: float | None = None
    recovery_score: float | None = None
    hrv_rmssd: float | None = None
    elevation_gain: float | None = None
    avg_power_watts: float | None = None
    raw_data: dict = {}


class WorkoutResponse(BaseModel):
    id: uuid.UUID
    platform: str
    sport_type: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    distance_meters: float | None
    calories: float | None
    avg_heart_rate: float | None
    max_heart_rate: float | None
    strain_score: float | None
    elevation_gain: float | None
    avg_power_watts: float | None
    created_at: datetime

    model_config = {"from_attributes": True}
