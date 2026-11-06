"""
Create (or reset the password of) an admin account. Public registration refuses admin emails because there
is no email verification - this script is the only way to create one.

    uv run python scripts/create_admin.py                       # prompts for name + password
    uv run python scripts/create_admin.py --email you@x.com     # must be listed in ADMIN_EMAILS
    ADMIN_PASSWORD=... uv run python scripts/create_admin.py --password-from-env   (automation)
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator.service import use_selector_event_loop  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.schemas.auth import UserCreate  # noqa: E402


async def main() -> None:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", default=s.admin_emails[0] if s.admin_emails else None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--password-from-env", action="store_true", help="read the password from ADMIN_PASSWORD")
    args = ap.parse_args()

    if not args.email or not s.is_admin_email(args.email):
        sys.exit(f"{args.email!r} is not listed in ADMIN_EMAILS ({', '.join(s.admin_emails) or 'empty'})")
    name = args.name or input("Full name: ").strip() or "Administrator"
    if args.password_from_env:
        password = os.environ.get("ADMIN_PASSWORD", "")
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            sys.exit("passwords do not match")
    try:
        UserCreate(email=args.email, full_name=name, password=password)  # same validation as registration
    except ValidationError as e:
        # never echo the input: the default error message would print the password
        problems = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors(include_input=False))
        sys.exit(f"invalid input - {problems}")

    db = Database(s.database_url)
    try:
        async with db.sessionmaker() as session:
            user = (await session.execute(select(User).where(User.email == args.email.lower()))).scalar_one_or_none()
            if user is None:
                session.add(User(email=args.email.lower(), full_name=name, password_hash=hash_password(password)))
                action = "created"
            else:
                user.password_hash, user.full_name, user.is_active = hash_password(password), name, True
                action = "updated (password reset)"
            await session.commit()
        print(f"admin account {args.email} {action}")
    finally:
        await db.dispose()


if __name__ == "__main__":
    use_selector_event_loop()
    asyncio.run(main())
