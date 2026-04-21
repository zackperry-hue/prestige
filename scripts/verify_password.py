"""Locally verify a password against the stored hash for a user.

Prompts for the password via getpass (hidden input). Does not print it.
Does not modify the database. Outputs only "MATCH" / "NO MATCH".

Usage:
    .venv/bin/python scripts/verify_password.py user@example.com
"""

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.user import User
from app.services.password import verify_password


async def check(email: str):
    engine = create_async_engine(
        settings.database_url,
        connect_args={"statement_cache_size": 0},
    )
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if not user:
            print(f"NO USER with email {email!r}")
            await engine.dispose()
            return

        print(f"User found. id={user.id}  hash_prefix={user.password_hash[:7]}  hash_len={len(user.password_hash)}")
        pw = getpass.getpass("Enter password (hidden): ")
        if verify_password(pw, user.password_hash):
            print("MATCH — the password is correct for the stored hash.")
        else:
            print("NO MATCH — the stored hash does not verify this password.")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: .venv/bin/python scripts/verify_password.py <email>")
        sys.exit(1)
    asyncio.run(check(sys.argv[1]))
