#!/usr/bin/env python
"""
Seed the first administrator, or promote an existing account.

Registration cannot grant `admin` (or `support`): the API only accepts the
participant roles, because those are onboarding intents rather than authority.
An administrator comes from the server's shell, where operating the deployment
is already possible:

    ./run.sh create-admin you@example.com
    ./run.sh create-admin ops@example.com --name "Ops" --password-stdin < secret

A new account is asked for a password twice (never echoed). An account that
already exists is promoted as it is and keeps its password, so the same command
is safe to run again and cannot lock anybody out.

Exit codes: 0 done, 2 refused (bad email, short password, no terminal to prompt
on). The password is never printed, logged, or passed on a command line.
"""

import argparse
import asyncio
import getpass
import sys
from typing import List, Optional

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.audit import ROLE_CHANGED, change_role, record_event
from app.core.security import hash_password
from app.database import Base, async_session_factory
from app.models.general import UserRole
from app.models.user_orm import UserRecord

MIN_PASSWORD_LENGTH = 8
_EMAIL = TypeAdapter(EmailStr)


class Refused(Exception):
    """The command will not do what was asked; exit code 2."""


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="create_admin.py",
        description="Create an administrator, or promote an existing account.",
        epilog=(
            "Registration cannot grant admin. Run this from the backend "
            "directory, or as ./run.sh create-admin EMAIL."
        ),
    )
    parser.add_argument("email", help="address of the administrator account")
    parser.add_argument(
        "--name",
        default="Administrator",
        help="display name for a new account (ignored when promoting)",
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help=(
            "read the new password from the first line of stdin instead of "
            "prompting; needed when the command runs without a terminal"
        ),
    )
    return parser.parse_args(argv)


def _read_password(from_stdin: bool) -> str:
    """Take a new password without putting it in the process arguments."""
    if from_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        if not sys.stdin.isatty():
            raise Refused(
                "no terminal to prompt on; pass --password-stdin to supply the "
                "password on stdin"
            )
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Repeat password: ")
        if password != confirm:
            raise Refused("passwords do not match")

    if len(password) < MIN_PASSWORD_LENGTH:
        raise Refused(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    return password


async def _run(email: str, name: str, password_from_stdin: bool) -> str:
    """Promote the account if it exists, otherwise create it."""
    async with async_session_factory() as session:
        # The command may be the first thing to touch a fresh deployment. Create
        # the one table it reads; the server's startup creates the rest. This
        # runs on the session's own connection so it follows whichever engine
        # the factory hands out.
        connection = await session.connection()
        await connection.run_sync(Base.metadata.create_all)
        # Commit the DDL on its own: Postgres would otherwise roll the new table
        # back when this session closes, leaving nothing for the next run.
        await session.commit()

        existing = await session.scalar(
            select(UserRecord).where(UserRecord.email == email)
        )
        if existing is not None:
            # The command is the actor: there is no signed-in account behind it,
            # so the trail says "cli" rather than naming somebody who was not
            # there.
            change_role(
                session,
                existing,
                UserRole.ADMIN.value,
                detail="create-admin",
                actor=None,
                actor_kind="cli",
            )
            existing.is_approved = True
            await session.commit()
            return (
                f"{email} is now an administrator "
                "(existing account promoted; its password is unchanged)"
            )

    password = _read_password(password_from_stdin)

    async with async_session_factory() as session:
        user = UserRecord(
            email=email,
            name=name,
            password_hash=hash_password(password),
            role=UserRole.ADMIN.value,
            # An administrator is trusted by construction, not by approval.
            is_approved=True,
        )
        session.add(user)
        try:
            # Flush assigns the user id the audit row points at, and keeps both
            # insertions in one transaction.
            await session.flush()
            record_event(
                session,
                action=ROLE_CHANGED,
                subject_type="user",
                subject_id=user.user_id,
                from_value="",
                to_value=UserRole.ADMIN.value,
                actor_kind="cli",
                detail="create-admin",
            )
            await session.commit()
        except IntegrityError as exc:
            raise Refused(
                "that address was registered while the command ran; run it "
                "again to promote the new account"
            ) from exc

    return f"created administrator {email}"


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        email = str(_EMAIL.validate_python(args.email))
        message = asyncio.run(_run(email, args.name, args.password_stdin))
    except ValidationError as exc:
        print(f"refusing: {exc.errors()[0]['msg']}", file=sys.stderr)
        return 2
    except Refused as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2

    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
