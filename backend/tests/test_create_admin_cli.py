"""The create-admin command: what it makes, what it refuses, what it proves.

Registration cannot grant `admin`, so this command is the only way an
administrator comes into existence. The tests drive the interface a person uses
(`./run.sh create-admin`) and then make the resulting account do admin work, so
a "success" means a usable administrator rather than a row with a role string.
"""

import io
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import create_admin as cli

PASSWORD = "passw0rd123"


@pytest.fixture
def cli_database(client, monkeypatch):
    """Give the command its own engine, inside the loop it opens with asyncio.run.

    Depends on `client` so the app's lifespan has created the schema first.
    """
    from app.database import DATABASE_URL

    @asynccontextmanager
    async def factory():
        engine = create_async_engine(DATABASE_URL)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    monkeypatch.setattr(cli, "async_session_factory", factory)


@pytest.fixture
def empty_cli_database(monkeypatch, tmp_path):
    """A database file with nothing in it: the first run on a fresh deployment."""

    @asynccontextmanager
    async def factory():
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(tmp_path / 'fresh.db').as_posix()}"
        )
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    monkeypatch.setattr(cli, "async_session_factory", factory)


def email_for(prefix: str = "admin") -> str:
    return f"{prefix}-{uuid.uuid4().hex}@example.com"


def supply_stdin(monkeypatch, text: str) -> None:
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(text + "\n"))


def login(client, email: str, password: str = PASSWORD):
    return client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )


def test_it_works_before_the_server_has_ever_run(
    empty_cli_database, monkeypatch, capsys
):
    """Seeding the first admin must not require starting the API first."""
    email = email_for()
    supply_stdin(monkeypatch, PASSWORD)

    assert cli.main([email, "--password-stdin"]) == 0
    assert "created administrator" in capsys.readouterr().out

    # The second run finds the account, which proves the table was created and
    # the row survived the first command's connection closing.
    assert cli.main([email]) == 0
    assert "promoted" in capsys.readouterr().out


def test_it_creates_an_administrator_who_can_actually_act_as_one(
    client, cli_database, monkeypatch, capsys, register, create_organization
):
    email = email_for()
    supply_stdin(monkeypatch, PASSWORD)

    assert cli.main([email, "--password-stdin"]) == 0

    output = capsys.readouterr()
    assert email in output.out
    assert PASSWORD not in output.out
    assert PASSWORD not in output.err

    signed_in = login(client, email)
    assert signed_in.status_code == 200, signed_in.text
    body = signed_in.json()
    assert body["user"]["role"] == "admin"
    assert body["user"]["is_approved"] is True
    admin_headers = {"Authorization": f"Bearer {body['access_token']}"}

    # The grant itself is on the trail, attributed to the command rather than
    # to an account that was not there.
    trail = client.get(
        "/api/admin/audit",
        params={"subject_id": body["user"]["user_id"]},
        headers=admin_headers,
    )
    assert trail.status_code == 200, trail.text
    events = trail.json()
    assert len(events) == 1
    assert events[0]["action"] == "user.role_changed"
    assert events[0]["from_value"] == ""
    assert events[0]["to_value"] == "admin"
    assert events[0]["actor_id"] is None
    assert events[0]["actor_kind"] == "cli"
    # A command has no role of its own; it must not be attributed the subject's
    # previous one.
    assert events[0]["actor_role"] == ""
    assert events[0]["detail"] == "create-admin"

    # The role is not just a label: it opens the admin gate.
    _, owner_headers = register()
    organization = create_organization(owner_headers)
    verified = client.put(
        f"/api/admin/organizations/{organization['org_id']}/verify",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["is_verified"] is True


def test_promoting_an_existing_account_keeps_its_password(
    client, cli_database, register, capsys
):
    user, headers = register()

    assert cli.main([user["email"]]) == 0

    output = capsys.readouterr().out
    assert "promoted" in output
    assert PASSWORD not in output

    # The token issued before the promotion still opens the admin gate: the
    # gate reads the role from the database, not from the token's old claim.
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "admin"

    trail = client.get(
        "/api/admin/audit",
        params={"subject_id": user["user_id"]},
        headers=headers,
    )
    assert trail.status_code == 200, trail.text
    events = trail.json()
    assert len(events) == 1
    assert events[0]["from_value"] == "customer"
    assert events[0]["to_value"] == "admin"
    assert events[0]["actor_id"] is None
    assert events[0]["actor_kind"] == "cli"
    assert events[0]["actor_role"] == ""
    assert events[0]["detail"] == "create-admin"

    # And the account can still sign in with the password it already had.
    assert login(client, user["email"]).status_code == 200


def test_running_it_twice_is_idempotent(client, cli_database, register, scalar):
    user, headers = register()

    assert cli.main([user["email"]]) == 0
    assert cli.main([user["email"]]) == 0

    count = scalar(
        "select count(*) from users where email = ?", (user["email"],)
    )
    assert count == 1
    assert scalar(
        "select role from users where email = ?", (user["email"],)
    ) == "admin"

    # The second run found the account already an admin, so the trail still has
    # exactly the one transition rather than one per invocation.
    trail = client.get(
        "/api/admin/audit",
        params={"subject_id": user["user_id"]},
        headers=headers,
    )
    assert len(trail.json()) == 1


def test_a_short_password_is_refused_and_creates_nothing(
    client, cli_database, monkeypatch, capsys, scalar
):
    email = email_for()
    supply_stdin(monkeypatch, "short")

    assert cli.main([email, "--password-stdin"]) == 2

    assert "at least 8" in capsys.readouterr().err
    assert scalar("select user_id from users where email = ?", (email,)) is None


def test_an_invalid_email_is_refused_before_reading_a_password(
    client, cli_database, capsys
):
    assert cli.main(["not-an-email", "--password-stdin"]) == 2

    assert "refusing" in capsys.readouterr().err


class _Terminal(io.StringIO):
    """A stdin that claims to be a terminal, so the prompt path is taken."""

    def isatty(self) -> bool:  # noqa: D401 - the interface is the point
        return True


def test_the_default_path_prompts_twice(client, cli_database, monkeypatch, capsys):
    email = email_for()
    monkeypatch.setattr(cli.sys, "stdin", _Terminal())
    answers = iter([PASSWORD, PASSWORD])
    typed = []

    def answer(prompt: str = "") -> str:
        typed.append(prompt)
        return next(answers)

    monkeypatch.setattr(cli.getpass, "getpass", answer)

    assert cli.main([email, "--name", "Ops"]) == 0

    assert len(typed) == 2
    assert PASSWORD not in capsys.readouterr().out
    signed_in = login(client, email)
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["user"]["name"] == "Ops"


def test_a_mismatched_confirmation_is_refused(
    client, cli_database, monkeypatch, capsys, scalar
):
    email = email_for()
    monkeypatch.setattr(cli.sys, "stdin", _Terminal())
    answers = iter([PASSWORD, PASSWORD + "-different"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))

    assert cli.main([email]) == 2

    assert "do not match" in capsys.readouterr().err
    assert scalar("select user_id from users where email = ?", (email,)) is None


def test_a_new_account_needs_a_terminal_or_the_stdin_flag(
    client, cli_database, monkeypatch, capsys, scalar
):
    """Without a prompt and without --password-stdin the command must stop,
    not hang or invent a password."""
    email = email_for()
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(""))

    assert cli.main([email]) == 2

    assert "password-stdin" in capsys.readouterr().err
    assert scalar("select user_id from users where email = ?", (email,)) is None
