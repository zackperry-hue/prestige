"""add password_reset_tokens table and enable RLS on all tables

Revision ID: b2c3d4e5f6a7
Revises: d4e5f6a7b8c9
Create Date: 2026-03-31

Idempotent by design: the password_reset_tokens table was created
out-of-band in prod before this migration existed, so CREATE TABLE
and CREATE INDEX are issued as IF NOT EXISTS. ENABLE ROW LEVEL
SECURITY is already idempotent in Postgres.

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All tables in the public schema that need RLS
TABLES = [
    "users",
    "user_profiles",
    "platform_connections",
    "password_reset_tokens",
    "workouts",
    "workout_sessions",
    "email_log",
    "webhook_events",
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id),
            token VARCHAR(255) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_password_reset_tokens_token "
        "ON password_reset_tokens (token)"
    )

    # Enable RLS on all tables (without FORCE — the backend service role and
    # superuser bypass RLS automatically, which is what we want for background
    # jobs like the session emailer, Wahoo poller, and token refresher).
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # Revoke direct access from Supabase public-facing roles so that
    # anon/authenticated cannot query tables even without RLS policies.
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated")


def downgrade() -> None:
    # Re-grant default access (restores Supabase defaults)
    op.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated")

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP INDEX IF EXISTS ix_password_reset_tokens_token")
    op.execute("DROP TABLE IF EXISTS password_reset_tokens")
