"""Diagnose why a user isn't receiving session emails.

Usage:
    python scripts/debug_email_delivery.py user@example.com

Run this in whatever env the worker is using (locally with .env loaded, or via
`railway run python scripts/debug_email_delivery.py ...` against prod).
"""

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.connection import PlatformConnection
from app.models.email_log import EmailLog
from app.models.user import User
from app.models.workout_session import WorkoutSession


def fmt(dt: datetime | None) -> str:
    return dt.isoformat() if dt else "—"


async def diagnose(email: str):
    print(f"\n=== ENVIRONMENT ===")
    print(f"  SENDGRID_API_KEY set:   {bool(settings.sendgrid_api_key)}")
    print(f"  SENDGRID_FROM_EMAIL:    {getattr(settings, 'sendgrid_from_email', '—')}")
    print(f"  DATABASE_URL host:      {settings.database_url.split('@')[-1].split('/')[0] if '@' in settings.database_url else '—'}")

    engine = create_async_engine(
        settings.database_url,
        connect_args={"statement_cache_size": 0},
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if not user:
            print(f"\n!! No user found with email '{email}'")
            await engine.dispose()
            return

        print(f"\n=== USER ===")
        print(f"  id:            {user.id}")
        print(f"  email:         {user.email}")
        print(f"  display_name:  {user.display_name}")
        print(f"  email_enabled: {user.email_enabled}  {'' if user.email_enabled else '  <-- SILENTLY SKIPS + MARKS email_sent_at'}")
        print(f"  timezone:      {user.timezone}")
        print(f"  created_at:    {fmt(user.created_at)}")

        conns = (
            await db.execute(
                select(PlatformConnection).where(PlatformConnection.user_id == user.id)
            )
        ).scalars().all()

        print(f"\n=== PLATFORM CONNECTIONS ({len(conns)}) ===")
        for c in conns:
            print(
                f"  {c.platform:8s} | active={c.is_active} | "
                f"connected={fmt(c.created_at)} | last_poll={fmt(c.last_poll_at)}"
            )
        print("  (workouts started BEFORE connected_at get email_scheduled_at=NULL and never fire)")

        sessions = (
            await db.execute(
                select(WorkoutSession)
                .where(WorkoutSession.user_id == user.id)
                .order_by(WorkoutSession.started_at.desc())
                .limit(15)
            )
        ).scalars().all()

        now = datetime.now(UTC)
        print(f"\n=== RECENT SESSIONS ({len(sessions)}) ===")
        print(f"  now = {now.isoformat()}")
        print(f"  {'started_at':<32} {'scheduled':<32} {'sent':<32} {'att':<4} {'platforms':<20} verdict")
        for s in sessions:
            if s.email_sent_at:
                verdict = "sent"
            elif s.email_scheduled_at is None:
                verdict = "NULL schedule (historical, skipped)"
            elif s.email_scheduled_at > now:
                verdict = f"waiting ({(s.email_scheduled_at - now)})"
            elif s.email_attempts >= 3:
                verdict = "GAVE UP (attempts >= 3)"
            else:
                verdict = "READY but not sent (check worker logs)"
            print(
                f"  {fmt(s.started_at):<32} {fmt(s.email_scheduled_at):<32} "
                f"{fmt(s.email_sent_at):<32} {s.email_attempts:<4} "
                f"{(s.platforms or ''):<20} {verdict}"
            )

        logs = (
            await db.execute(
                select(EmailLog)
                .where(EmailLog.user_id == user.id)
                .order_by(EmailLog.sent_at.desc())
                .limit(15)
            )
        ).scalars().all()

        print(f"\n=== EMAIL_LOG ENTRIES ({len(logs)}) ===")
        if not logs:
            print("  !! No email_log rows. Either nothing ever tried to send,")
            print("     or SENDGRID_API_KEY was missing (early-returns before log row is added).")
        for log in logs:
            print(
                f"  {fmt(log.sent_at)} | status={log.status:7s} | "
                f"sg_msg_id={log.sendgrid_msg_id or '—'}"
            )
            if log.error_message:
                print(f"    error: {log.error_message[:300]}")

        ready_now = (
            await db.execute(
                select(WorkoutSession).where(
                    WorkoutSession.user_id == user.id,
                    WorkoutSession.email_scheduled_at <= now,
                    WorkoutSession.email_sent_at.is_(None),
                    WorkoutSession.email_attempts < 3,
                )
            )
        ).scalars().all()

        print(f"\n=== SESSIONS CURRENTLY MATCHING get_sessions_ready_to_email() ===")
        print(f"  count: {len(ready_now)}")
        for s in ready_now:
            print(f"  {s.id} started={fmt(s.started_at)} scheduled={fmt(s.email_scheduled_at)} attempts={s.email_attempts}")

        recent_cutoff = now - timedelta(hours=48)
        orphan = (
            await db.execute(
                select(WorkoutSession).where(
                    WorkoutSession.user_id == user.id,
                    WorkoutSession.started_at >= recent_cutoff,
                    WorkoutSession.email_scheduled_at.is_(None),
                )
            )
        ).scalars().all()

        if orphan:
            print(f"\n!! {len(orphan)} session(s) in last 48h have email_scheduled_at=NULL:")
            for s in orphan:
                print(f"  {s.id} started={fmt(s.started_at)} platforms={s.platforms}")
            print("  These will NEVER be emailed. Likely reasons:")
            print("    - workout predates platform connection (historical skip, by design)")
            print("    - merged-session bug from before commit 6ac2135")

    await engine.dispose()

    print(f"\n=== NEXT STEPS ===")
    print("  - No email_log rows + scheduled sessions exist → SENDGRID_API_KEY missing or scheduler not running")
    print("  - email_log rows with status='failed' → check error_message; SendGrid auth or sender verification")
    print("  - email_log rows with status='sent' but user didn't receive → spam folder / DNS (SPF/DKIM/DMARC)")
    print("  - email_enabled=False → re-enable in DB; existing sessions still blocked (email_sent_at already set)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/debug_email_delivery.py <user_email>")
        sys.exit(1)
    asyncio.run(diagnose(sys.argv[1]))
