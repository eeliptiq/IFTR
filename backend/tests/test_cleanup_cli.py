"""The cleanup command: flags, exit codes, and what it reports.

These cover the interface a person actually uses - `./run.sh cleanup-uploads` -
so its exit codes stop being something only a terminal session can confirm.
"""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import cleanup_uploads as cli


@pytest.fixture
def cli_database(monkeypatch):
    """Point the command at a session factory owned by this test's event loop.

    The app's own engine belongs to the loop the TestClient runs, and a
    connection cannot be reused across event loops, so the command gets its own.
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
    """Point the command at a database with no tables at all."""

    @asynccontextmanager
    async def factory():
        engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'nothing.db').as_posix()}")
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    monkeypatch.setattr(cli, "async_session_factory", factory)


def test_a_dry_run_reports_and_deletes_nothing(cli_database, managed_upload, capsys):
    orphan = managed_upload()

    assert cli.main([]) == 0

    output = capsys.readouterr().out
    assert orphan.name in output
    assert "re-run with --delete" in output
    assert orphan.exists()


def test_delete_removes_the_orphans_and_exits_zero(cli_database, managed_upload, capsys, populated_database):
    orphan = managed_upload()

    assert cli.main(["--delete"]) == 0

    assert not orphan.exists()
    assert "reclaimed" in capsys.readouterr().out


def test_the_age_floor_holds_until_it_is_lowered_explicitly(
    cli_database, managed_upload, populated_database
):
    fresh = managed_upload(age_minutes=1)

    assert cli.main(["--delete"]) == 0
    assert fresh.exists(), "the default hour protects a just-uploaded file"

    assert cli.main(["--delete", "--min-age-minutes", "0"]) == 0
    assert not fresh.exists()


def test_an_empty_database_exits_two_and_deletes_nothing(empty_cli_database, managed_upload, capsys):
    orphan = managed_upload()

    assert cli.main(["--delete", "--min-age-minutes", "0"]) == 2

    captured = capsys.readouterr()
    assert "refusing to delete" in captured.err
    assert orphan.exists()


def test_no_log_leaves_no_trace(cli_database, managed_upload, sweep_log, capsys):
    managed_upload()

    assert cli.main(["--no-log"]) == 0

    assert not sweep_log.exists()
    assert "logged this run" not in capsys.readouterr().out


def test_the_log_can_be_sent_somewhere_else(
    cli_database, managed_upload, tmp_path, sweep_log, capsys
):
    managed_upload()
    elsewhere = tmp_path / "my-history.log"

    assert cli.main(["--log-file", str(elsewhere)]) == 0

    assert "dry run" in elsewhere.read_text()
    assert not sweep_log.exists()
