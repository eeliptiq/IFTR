"""
Shared setup for the backend test suite.

The suite must never touch real data, so a throwaway database, uploads directory
and cleanup log are configured here *before* the app package is imported - those
modules read their paths at import time. Running `pytest` therefore leaves a
developer's backend/iftr.db and backend/uploads/ completely alone.

The tests use FastAPI's TestClient for HTTP (which runs the real lifespan, so
tables are created the same way the server creates them) and build their own
short-lived database engines for direct queries and sweeps.
"""

import asyncio
import base64
import gc
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# --------------------------------------------------------------------------
# Isolation: point the app at throwaway paths before importing anything of it.
# --------------------------------------------------------------------------
_TMP = Path(tempfile.mkdtemp(prefix="iftr-tests-"))

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["UPLOADS_DIR"] = str(_TMP / "uploads")
os.environ["UPLOADS_GC_LOG"] = str(_TMP / "logs" / "uploads_cleanup.log")
# Tests drive the sweep themselves rather than leaving a timer running.
os.environ["UPLOADS_GC_INTERVAL_MINUTES"] = "0"
# Keep the app's own logging from drowning the test report.
os.environ["LOG_LEVEL"] = "WARNING"
os.environ.setdefault("ENCRYPTION_KEY", "iftr-test-encryption-key")
# Payments tests install their own fake gateway. A developer's real Stripe key
# must never be reachable from the suite, and an absent key is itself a state
# one of the tests asserts (checkout answers 503 instead of charging).
os.environ.pop("STRIPE_SECRET_KEY", None)
os.environ.pop("STRIPE_WEBHOOK_SECRET", None)

DATABASE_URL = os.environ["DATABASE_URL"]

# A real (1x1) PNG plus signature-correct samples of the other accepted types.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)
IMAGE_BYTES = {
    "png": PNG_BYTES,
    "jpeg": b"\xff\xd8\xff\xe0" + b"\x00" * 32,
    "gif": b"GIF89a" + b"\x00" * 32,
    "webp": b"RIFF" + (32).to_bytes(4, "little") + b"WEBP" + b"\x00" * 32,
}
EXTENSIONS = {"png": ".png", "jpeg": ".jpg", "gif": ".gif", "webp": ".webp"}


@pytest.fixture(scope="session", autouse=True)
def _throwaway_workspace():
    """Discard the temporary database, uploads and log once the session is over."""
    yield
    import shutil
    import time

    from app import database

    # Release the app's pooled SQLite connections first. Left open, the database
    # file stays locked and Windows refuses to remove the directory.
    asyncio.run(database.engine.dispose())
    gc.collect()

    # Windows can hold the directory itself for a while after the last handle
    # goes, so retry instead of leaving an empty directory behind. The budget is
    # larger than it looks like it should need on purpose: in a long session a
    # stale handle can outlive the tests by a second or two, and a run that
    # tidies up after itself is worth a few seconds of patience.
    for _ in range(25):
        shutil.rmtree(_TMP, ignore_errors=True)
        if not _TMP.exists():
            break
        gc.collect()
        time.sleep(0.2)


@pytest.fixture(scope="session")
def client():
    """The app behind a TestClient, with its lifespan (and schema) run once."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _open_session():
    """An engine + session factory used entirely inside one event loop."""
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


@pytest.fixture
def uploads_dir() -> Path:
    """The uploads directory the app is writing to (a temporary one)."""
    from app.api.uploads import UPLOAD_DIR

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


@pytest.fixture
def sweep_log() -> Path:
    """Where the cleanup run history goes (a temporary file)."""
    from app.uploads_gc import LOG_PATH

    return LOG_PATH


@pytest.fixture(autouse=True)
def isolated_uploads(uploads_dir, sweep_log):
    """Every test starts with an empty uploads directory and no run history."""
    for entry in uploads_dir.iterdir():
        if entry.is_file():
            entry.unlink()
    sweep_log.unlink(missing_ok=True)
    yield


@pytest.fixture
def image_bytes():
    return IMAGE_BYTES


@pytest.fixture
def managed_upload(uploads_dir) -> Callable[..., Path]:
    """Write a file into the uploads directory, as the sweep would find it."""

    def _make(
        name: Optional[str] = None,
        age_minutes: float = 180,
        content: bytes = PNG_BYTES,
    ) -> Path:
        path = uploads_dir / (name or f"{uuid.uuid4().hex}.png")
        path.write_bytes(content)
        stamp = time.time() - age_minutes * 60
        os.utime(path, (stamp, stamp))
        return path

    return _make


@pytest.fixture
def sweep(client):
    """Run the uploads sweep the way the CLI does, from a synchronous test.

    Depends on `client` so the app's lifespan has created the schema first: a
    sweep against a database with no tables is *supposed* to refuse.
    """

    def _sweep(**kwargs):
        from app.uploads_gc import cleanup_uploads

        async def run():
            engine, factory = _open_session()
            try:
                async with factory() as session:
                    return await cleanup_uploads(session, **kwargs)
            finally:
                await engine.dispose()

        return asyncio.run(run())

    return _sweep


@pytest.fixture
def scalar(client):
    """Read one value straight out of the test database.

    Uses raw SQL on purpose: these assertions are about what is actually stored,
    not about what the ORM would like to hand back.
    """

    def _scalar(sql: str, params: tuple = ()):
        async def run():
            engine, _ = _open_session()
            try:
                async with engine.begin() as connection:
                    result = await connection.exec_driver_sql(sql, params)
                    return result.scalar()
            finally:
                await engine.dispose()

        return asyncio.run(run())

    return _scalar


@pytest.fixture
def execute(client) -> Callable[..., int]:
    """Change rows straight in the test database; return how many were touched.

    `scalar` reads one value and therefore cannot run an UPDATE. Some tests need
    to state a precondition that no endpoint can ("this is the only admin"), so
    the statement runs on its own committed connection.
    """

    def _execute(sql: str, params: tuple = ()) -> int:
        async def run():
            engine, _ = _open_session()
            try:
                async with engine.begin() as connection:
                    result = await connection.exec_driver_sql(sql, params)
                    return result.rowcount
            finally:
                await engine.dispose()

        return asyncio.run(run())

    return _execute


@pytest.fixture
def register(client) -> Callable[..., tuple]:
    """Register a user and return (user dict, auth headers)."""

    def _register(role: str = "customer", **overrides):
        payload = {
            "email": f"{uuid.uuid4().hex}@example.com",
            "password": "passw0rd123",
            "name": "Test User",
            "role": role,
            **overrides,
        }
        response = client.post("/api/auth/register", json=payload)
        assert response.status_code == 201, response.text
        body = response.json()
        return body["user"], {"Authorization": f"Bearer {body['access_token']}"}

    return _register


@pytest.fixture
def populated_database(register) -> dict:
    """Give the database a row, the way any running server has.

    The sweep refuses to delete anything when no mapped table holds a single row
    (its guard against the wrong DATABASE_URL), so a test that expects files to
    be reclaimed needs this precondition stated rather than inherited from
    whatever earlier tests happened to leave behind.

    Returns the new user's auth headers, in case the test wants them.
    """
    _, headers = register()
    return headers


@pytest.fixture
def create_restaurant(client) -> Callable[..., dict]:
    """Register a restaurant for whoever owns the given headers."""

    def _create(headers, **overrides):
        payload = {
            "name": "Test Kitchen",
            "description": "",
            "cuisine_type": "italian",
            "image_url": None,
            "lat": 40.7,
            "lng": -74.0,
            "address": "1 Test St",
            "city": "NYC",
            "zip_code": "10001",
            **overrides,
        }
        response = client.post("/api/restaurants", json=payload, headers=headers)
        assert response.status_code == 201, response.text
        return response.json()

    return _create


@pytest.fixture
def create_organization(client) -> Callable[..., dict]:
    """Register an organization for whoever owns the given headers."""

    def _create(headers, **overrides):
        payload = {
            "name": "Test Food Bank",
            "description": "A pantry",
            "org_type": "food_bank",
            "lat": 40.71,
            "lng": -74.0,
            "address": "2 Org Ave",
            "city": "NYC",
            "contact_email": "help@example.org",
            "contact_phone": "555-0100",
            **overrides,
        }
        response = client.post("/api/organizations", json=payload, headers=headers)
        assert response.status_code == 201, response.text
        return response.json()

    return _create


@pytest.fixture
def admin_user(client, register) -> Callable[..., tuple]:
    """A signed-in account promoted to admin directly in the database.

    The HTTP API cannot grant `admin` on purpose, and the command that can is
    covered by tests/test_create_admin_cli.py. Tests that merely need the role
    flip the row, the same way the command does, and keep the token they already
    hold: authorization reads the role from the database.
    """

    def _make() -> tuple:
        from sqlalchemy import update

        from app.models.user_orm import UserRecord

        user, headers = register()

        async def run():
            engine, factory = _open_session()
            try:
                async with factory() as session:
                    await session.execute(
                        update(UserRecord)
                        .where(UserRecord.user_id == user["user_id"])
                        .values(role="admin", is_approved=True)
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(run())
        return user, headers

    return _make


@pytest.fixture
def verify_organization(client) -> Callable[..., None]:
    """Mark an organization verified, the way the admin slice will.

    Nothing in the API can verify an organization yet, and reserving requires
    it, so the tests state that precondition directly instead of going through a
    route that does not exist.
    """

    def _verify(org_id: str, verified: bool = True) -> None:
        from sqlalchemy import update

        from app.models.organization_orm import OrganizationRecord

        async def run():
            engine, factory = _open_session()
            try:
                async with factory() as session:
                    await session.execute(
                        update(OrganizationRecord)
                        .where(OrganizationRecord.org_id == org_id)
                        .values(is_verified=verified)
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(run())

    return _verify


@pytest.fixture
def set_surplus_expiry(client) -> Callable[..., None]:
    """Move a listing's expiry, so "expired" can be tested without waiting."""

    def _set(surplus_id: str, when) -> None:
        from sqlalchemy import update

        from app.models.surplus_food_orm import SurplusFoodRecord

        async def run():
            engine, factory = _open_session()
            try:
                async with factory() as session:
                    await session.execute(
                        update(SurplusFoodRecord)
                        .where(SurplusFoodRecord.surplus_id == surplus_id)
                        .values(expiry_time=when)
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(run())

    return _set


@pytest.fixture
def register_driver(client, register) -> Callable[..., tuple]:
    """Create a user and sign them up as a driver: (user, headers, driver)."""

    def _register(vehicle_type: str = "car", license_number: str = "DL-0001"):
        user, headers = register()
        response = client.post(
            "/api/drivers/register",
            json={"vehicle_type": vehicle_type, "license_number": license_number},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        return user, headers, response.json()

    return _register


@pytest.fixture
def seed_order(client) -> Callable[..., dict]:
    """Put an order in the test database and return the row that was written.

    Nothing in the API creates orders yet - customer checkout is a later slice -
    so the queue's tests state that precondition explicitly with a row written
    through the app's own model. The endpoints under test are still driven over
    HTTP. `created_at` can be overridden to make ordering assertions exact.

    Depends on `client` so the app's lifespan has created the schema first.
    """

    def _seed(
        restaurant_id: str,
        status: str = "pending",
        order_id: Optional[str] = None,
        items: Optional[list] = None,
        dropoff: Optional[tuple] = None,
        **overrides,
    ) -> dict:
        """`dropoff` is a (lat, lng) pair for the customer's door.

        Optional, because the board has to cope with orders nobody has located
        yet; when given it is encrypted exactly as the app encrypts it, so the
        tests exercise the real read path rather than a plaintext shortcut.
        """
        from app.core.encryption import encrypt_data
        from app.models.order_orm import OrderLocationRecord, OrderRecord

        row = {
            "order_id": order_id or f"order_{uuid.uuid4().hex[:12]}",
            "restaurant_id": restaurant_id,
            "customer_id": "user_customer",
            "customer_name": "Test Customer",
            "items": items
            if items is not None
            else [
                {
                    "item_id": "item_1",
                    "name": "Margherita",
                    "quantity": 2,
                    "base_price": 12.5,
                }
            ],
            "subtotal": 25.0,
            "tax_amount": 2.0,
            "delivery_fee": 2.99,
            "tip_amount": 3.0,
            "total_amount": 32.99,
            "status": status,
            "delivery_address": "9 Customer Rd",
            "delivery_city": "NYC",
            "delivery_zip": "10002",
            "delivery_instructions": "Leave at door",
            **overrides,
        }

        async def run():
            engine, factory = _open_session()
            try:
                async with factory() as session:
                    session.add(OrderRecord(**row))
                    if dropoff is not None:
                        session.add(
                            OrderLocationRecord(
                                order_id=row["order_id"],
                                lat_encrypted=encrypt_data(str(dropoff[0])),
                                lng_encrypted=encrypt_data(str(dropoff[1])),
                            )
                        )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(run())
        return row

    return _seed


@pytest.fixture
def upload_image(client) -> Callable[..., dict]:
    """Upload an image through the API and return the JSON response."""

    def _upload(headers, kind: str = "png", filename: Optional[str] = None, content: Optional[bytes] = None):
        body = content if content is not None else IMAGE_BYTES[kind]
        name = filename or f"photo{EXTENSIONS.get(kind, '.png')}"
        response = client.post(
            "/api/uploads",
            files={"file": (name, body, f"image/{'jpeg' if kind == 'jpeg' else kind}")},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _upload
