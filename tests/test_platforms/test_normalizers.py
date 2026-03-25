"""Tests for platform workout normalizers."""

from datetime import UTC, datetime

from app.platforms.strava_client import normalize_strava_activity
from app.platforms.wahoo_client import normalize_wahoo_workout
from app.platforms.whoop_client import normalize_whoop_workout


class TestStravaNormalizer:
    def test_running_activity(self):
        data = {
            "id": 12345678,
            "type": "Run",
            "start_date": "2026-03-25T08:30:00Z",
            "elapsed_time": 1845,
            "moving_time": 1800,
            "distance": 5012.3,
            "total_elevation_gain": 42.0,
            "average_heartrate": 155.2,
            "max_heartrate": 178.0,
            "calories": 420.5,
            "average_watts": None,
        }
        result = normalize_strava_activity(data)

        assert result.platform == "strava"
        assert result.platform_workout_id == "12345678"
        assert result.sport_type == "running"
        assert result.duration_seconds == 1845
        assert result.distance_meters == 5012.3
        assert result.avg_heart_rate == 155.2
        assert result.max_heart_rate == 178.0
        assert result.calories == 420.5
        assert result.elevation_gain == 42.0
        assert result.strain_score is None
        assert result.avg_power_watts is None

    def test_cycling_activity(self):
        data = {
            "id": 99887766,
            "type": "Ride",
            "start_date": "2026-03-24T16:00:00Z",
            "elapsed_time": 3600,
            "distance": 30000.0,
            "total_elevation_gain": 350.0,
            "average_heartrate": 140.0,
            "max_heartrate": 165.0,
            "calories": 800.0,
            "average_watts": 210.0,
        }
        result = normalize_strava_activity(data)

        assert result.sport_type == "cycling"
        assert result.distance_meters == 30000.0
        assert result.avg_power_watts == 210.0
        assert result.elevation_gain == 350.0

    def test_virtual_ride_maps_to_cycling(self):
        data = {
            "id": 11111,
            "type": "VirtualRide",
            "start_date": "2026-03-25T12:00:00Z",
            "elapsed_time": 2700,
            "distance": 20000.0,
        }
        result = normalize_strava_activity(data)
        assert result.sport_type == "cycling"

    def test_unknown_type_maps_to_other(self):
        data = {
            "id": 22222,
            "type": "SomeNewActivity",
            "start_date": "2026-03-25T12:00:00Z",
            "elapsed_time": 600,
        }
        result = normalize_strava_activity(data)
        assert result.sport_type == "other"

    def test_ended_at_calculated(self):
        data = {
            "id": 33333,
            "type": "Run",
            "start_date": "2026-03-25T08:00:00Z",
            "elapsed_time": 1800,
        }
        result = normalize_strava_activity(data)
        assert result.ended_at == datetime(2026, 3, 25, 8, 30, 0, tzinfo=UTC)

    def test_missing_optional_fields(self):
        data = {
            "id": 44444,
            "type": "Walk",
            "start_date": "2026-03-25T10:00:00Z",
            "elapsed_time": 900,
            "distance": 1200.0,
        }
        result = normalize_strava_activity(data)

        assert result.sport_type == "walking"
        assert result.calories is None
        assert result.avg_heart_rate is None
        assert result.max_heart_rate is None
        assert result.elevation_gain is None
        assert result.avg_power_watts is None


class TestWhoopNormalizer:
    def test_running_workout(self):
        data = {
            "id": "abc-123-def",
            "sport_id": 0,
            "start": "2026-03-25T07:00:00.000Z",
            "end": "2026-03-25T07:35:00.000Z",
            "score": {
                "strain": 12.5,
                "average_heart_rate": 162.0,
                "max_heart_rate": 185.0,
                "kilojoule": 1500.0,
                "distance_meter": 5200.0,
            },
        }
        result = normalize_whoop_workout(data)

        assert result.platform == "whoop"
        assert result.platform_workout_id == "abc-123-def"
        assert result.sport_type == "running"
        assert result.duration_seconds == 2100  # 35 min
        assert result.distance_meters == 5200.0
        assert result.avg_heart_rate == 162.0
        assert result.max_heart_rate == 185.0
        assert result.strain_score == 12.5
        # kilojoules converted to calories
        assert result.calories is not None
        assert abs(result.calories - 358.5) < 1.0

    def test_strength_workout_no_distance(self):
        data = {
            "id": "xyz-789",
            "sport_id": 2,
            "start": "2026-03-25T17:00:00.000Z",
            "end": "2026-03-25T18:00:00.000Z",
            "score": {
                "strain": 8.2,
                "average_heart_rate": 120.0,
                "max_heart_rate": 145.0,
                "kilojoule": 800.0,
            },
        }
        result = normalize_whoop_workout(data)

        assert result.sport_type == "strength"
        assert result.duration_seconds == 3600
        assert result.distance_meters is None
        assert result.strain_score == 8.2

    def test_empty_score(self):
        data = {
            "id": "no-score-1",
            "sport_id": -1,
            "start": "2026-03-25T12:00:00.000Z",
            "end": "2026-03-25T12:30:00.000Z",
            "score": {},
        }
        result = normalize_whoop_workout(data)

        assert result.sport_type == "activity"
        assert result.avg_heart_rate is None
        assert result.strain_score is None
        assert result.calories is None


class TestWahooNormalizer:
    def test_cycling_workout(self):
        data = {
            "id": 55555,
            "workout_type_id": 1,
            "starts": "2026-03-25T06:00:00Z",
            "created_at": "2026-03-25T06:00:00Z",
            "workout_summary": {
                "duration_active_accum": 5400,
                "distance_accum": 40000.0,
                "calories_accum": 950.0,
                "heart_rate_avg": 138.0,
                "heart_rate_max": 160.0,
                "ascent_accum": 420.0,
                "power_avg": 195.0,
            },
        }
        result = normalize_wahoo_workout(data)

        assert result.platform == "wahoo"
        assert result.platform_workout_id == "55555"
        assert result.sport_type == "cycling"
        assert result.duration_seconds == 5400
        assert result.distance_meters == 40000.0
        assert result.calories == 950.0
        assert result.avg_heart_rate == 138.0
        assert result.max_heart_rate == 160.0
        assert result.elevation_gain == 420.0
        assert result.avg_power_watts == 195.0

    def test_running_workout(self):
        data = {
            "id": 66666,
            "workout_type_id": 12,
            "starts": "2026-03-25T08:00:00Z",
            "workout_summary": {
                "duration_active_accum": 2400,
                "distance_accum": 8000.0,
                "calories_accum": 600.0,
                "heart_rate_avg": 155.0,
                "heart_rate_max": 175.0,
            },
        }
        result = normalize_wahoo_workout(data)

        assert result.sport_type == "running"
        assert result.distance_meters == 8000.0
        assert result.avg_power_watts is None

    def test_empty_summary(self):
        data = {
            "id": 77777,
            "workout_type_id": 0,
            "starts": "2026-03-25T10:00:00Z",
            "workout_summary": None,
        }
        result = normalize_wahoo_workout(data)

        assert result.sport_type == "other"
        assert result.duration_seconds == 0
        assert result.distance_meters is None
        assert result.calories is None

    def test_falls_back_to_created_at(self):
        data = {
            "id": 88888,
            "workout_type_id": 1,
            "created_at": "2026-03-25T14:00:00Z",
            "workout_summary": {
                "duration_active_accum": 1800,
            },
        }
        result = normalize_wahoo_workout(data)
        assert result.started_at == datetime(2026, 3, 25, 14, 0, 0, tzinfo=UTC)
