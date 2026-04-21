"""Reset a user's password directly in the DB.

Prompts for the new password twice via getpass (hidden). Writes the
bcrypt hash to users.password_hash. Does not print the password.

Usage:
    .venv/bin/python scripts/reset_password.py user@example.com
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
from app.services.password import hash_password


async def reset(email: str):
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

        print(f"Resetting password for {user.email} (id={user.id})")
        pw1 = getpass.getpass("New password (hidden, min 8 chars): ")
        if len(pw1) < 8:
            print("Password must be at least 8 characters. Aborting.")
            await engine.dispose()
            return
        pw2 = getpass.getpass("Confirm new password: ")
        if pw1 != pw2:
            print("Passwords do not match. Aborting.")
            await engine.dispose()
            return

        user.password_hash = hash_password(pw1)
        await db.commit()
        print("Password updated. You can now sign in.")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: .venv/bin/python scripts/reset_password.py <email>")
        sys.exit(1)
    asyncio.run(reset(sys.argv[1]))
