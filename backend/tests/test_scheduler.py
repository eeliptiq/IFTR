"""The background sweep: interval config, unattended survival, and shutdown."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.uploads_gc_scheduler as scheduler
from app.uploads_gc import EmptyDatabaseError


def _run(coro):
    return asyncio.run(coro)


async def _wait_until(predicate, timeout: float = 10.0) -> bool:
    """Poll rather than sleep a fixed amount, so a slow machine is not a failure."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.mark.parametrize(
    "value, expected",
    [(None, 60.0), ("15", 15.0), ("0", 0.0), ("nonsense", 60.0), ("", 60.0)],
)
def test_the_interval_comes_from_the_environment(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("UPLOADS_GC_INTERVAL_MINUTES", raising=False)
    else:
        monkeypatch.setenv("UPLOADS_GC_INTERVAL_MINUTES", value)

    assert scheduler.configured_interval_minutes() == expected


def test_a_zero_interval_disables_the_sweep(monkeypatch, managed_upload, sweep_log):
    orphan = managed_upload()
    monkeypatch.setenv("UPLOADS_GC_INTERVAL_MINUTES", "0")

    _run(scheduler.sweep_forever())

    assert orphan.exists()
    assert not sweep_log.exists()


@pytest.fixture
def scheduler_database(client, monkeypatch):
    """Give the scheduler a session factory whose engine belongs to this test's loop.

    The app's own engine is bound to the loop the TestClient runs, and reusing a
    connection across event loops is not safe, so the scheduler gets its own.
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

    monkeypatch.setattr(scheduler, "async_session_factory", factory)


def test_the_running_sweep_reclaims_an_orphan_and_records_it(
    scheduler_database, managed_upload, sweep_log, populated_database
):
    orphan = managed_upload()

    async def scenario():
        task = asyncio.create_task(scheduler.sweep_forever(0.01))  # sweeps at once, then often
        reclaimed = await _wait_until(lambda: not orphan.exists())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return reclaimed

    assert _run(scenario()) is True
    history = sweep_log.read_text()
    assert "deleted:" in history and orphan.name in history


def test_idle_intervals_do_not_fill_the_log(scheduler_database, sweep_log):
    async def scenario():
        task = asyncio.create_task(scheduler.sweep_forever(0.005))  # ~10 sweeps
        await asyncio.sleep(0.8)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _run(scenario())
    assert not sweep_log.exists(), "a sweep with nothing to do should stay silent"


def test_a_refusal_does_not_stop_or_crash_the_schedule(monkeypatch, caplog):
    """Regression: the refusal path once fell through and killed the task."""
    attempts = []

    async def refusing(*args, **kwargs):
        attempts.append(1)
        raise EmptyDatabaseError("no rows at all")

    monkeypatch.setattr(scheduler, "cleanup_uploads", refusing)

    async def scenario():
        with caplog.at_level(logging.ERROR, logger=scheduler.__name__):
            task = asyncio.create_task(scheduler.sweep_forever(0.005))
            kept_going = await _wait_until(lambda: len(attempts) >= 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        return kept_going

    assert _run(scenario()) is True
    assert len(attempts) >= 3, "the schedule must keep trying"
    assert "refused to delete anything" in caplog.text


def test_a_crashing_iteration_does_not_stop_the_schedule(monkeypatch, caplog):
    attempts = []

    async def exploding(*args, **kwargs):
        attempts.append(1)
        raise RuntimeError("kaboom")

    monkeypatch.setattr(scheduler, "run_sweep_once", exploding)

    async def scenario():
        with caplog.at_level(logging.ERROR, logger=scheduler.__name__):
            task = asyncio.create_task(scheduler.sweep_forever(0.005))
            kept_going = await _wait_until(lambda: len(attempts) >= 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        return kept_going

    assert _run(scenario()) is True
    assert len(attempts) >= 3
    assert "iteration crashed; continuing" in caplog.text


def test_run_sweep_once_reports_a_failure_instead_of_raising(monkeypatch, caplog):
    async def exploding(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(scheduler, "cleanup_uploads", exploding)

    with caplog.at_level(logging.ERROR, logger=scheduler.__name__):
        _run(scheduler.run_sweep_once())  # must return normally

    assert "will retry" in caplog.text
    assert "RuntimeError" in caplog.text  # traceback preserved


def test_the_lifespan_starts_and_cancels_the_sweep(monkeypatch):
    """What makes the sweep automatic: the app starts it and stops it."""
    import app.main as main_module
    from app.main import app

    started = asyncio.Event()

    async def fake_init_db():
        return None

    async def fake_sweep_forever():
        started.set()
        await asyncio.Event().wait()  # run until cancelled

    monkeypatch.setattr(main_module, "init_db", fake_init_db)
    monkeypatch.setattr(main_module, "sweep_forever", fake_sweep_forever)

    async def scenario():
        async with main_module.lifespan(app):
            await asyncio.wait_for(started.wait(), timeout=5)
            running = {task.get_name() for task in asyncio.all_tasks()}
        leftover = {task.get_name() for task in asyncio.all_tasks() if "sweep" in task.get_name()}
        return running, leftover

    running, leftover = _run(scenario())

    assert "uploads-sweep" in running
    assert leftover == set(), "shutdown must not leave the sweep running"
