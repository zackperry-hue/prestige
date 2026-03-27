from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://workout:workout@localhost:5432/workout_tracker"

    # Security
    token_encryption_key: str = ""
    app_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Whoop
    whoop_client_id: str = ""
    whoop_client_secret: str = ""
    whoop_redirect_uri: str = "http://localhost:8000/auth/whoop/callback"
    whoop_webhook_secret: str = ""

    # Strava
    strava_client_id: str = ""
    strava_client_secret: str = ""
    strava_redirect_uri: str = "http://localhost:8000/auth/strava/callback"
    strava_verify_token: str = ""

    # Wahoo
    wahoo_client_id: str = ""
    wahoo_client_secret: str = ""
    wahoo_redirect_uri: str = "http://localhost:8000/auth/wahoo/callback"

    # SendGrid
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "workouts@yourapp.com"

    # Anthropic (Claude AI for workout narratives)
    anthropic_api_key: str = ""

    # App
    app_base_url: str = "http://localhost:8000"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
