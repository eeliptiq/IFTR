"""
The world both browser journeys walk into, built once for the whole session.

Starting uvicorn is cheap; compiling the CRA app is not. Running the two browser
modules against one dev server means the checkout and admin journeys share one
compile instead of paying for it twice. The cost is that the seed has to contain
both worlds even when only one module is selected - a handful of API calls,
against tens of seconds of webpack.

The fixture is session-scoped and imported into both test modules by name, so
pytest hands them the same instance. Each module wraps it in its own small
`stack` fixture to keep the test signatures about the world it uses.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterator, Optional

import httpx
import pytest

from tests.ui_harness import (
    BACKEND,
    FRONTEND,
    PASSWORD,
    free_port,
    register,
    skip_reason,
    spawn,
    stop,
    wait_for,
)

# One dish: the checkout journey is about the screens, and a drink would put the
# driver's cup-holder dialog in the middle of it.
MENU = [
    {
        "item_id": "item_shish",
        "name": "Lamb Shish",
        "description": "Grilled skewers",
        "price": 14.5,
    }
]
SUBTOTAL = 14.5
DELIVERY_FEE = 2.99
TIP = 3.0
TOTAL = round(SUBTOTAL + DELIVERY_FEE + TIP, 2)

ORGANIZATION = {
    "name": "Pending Pantry",
    "description": "Neighborhood pantry",
    "org_type": "food_bank",
    "lat": 40.7,
    "lng": -74.0,
    "address": "12 Market St",
    "city": "Newark",
    "contact_email": "hello@pendingpantry.org",
    "contact_phone": "555-0142",
}


@dataclass
class CheckoutWorld:
    """The restaurant, menu and accounts the order journey uses."""

    web_url: str
    restaurant_id: str
    item_id: str
    customer: str
    owner: str
    driver: str


@dataclass
class AdminWorld:
    """The accounts and the pending application the admin journeys use."""

    api_base: str
    web_url: str
    admin_email: str
    user_id: str
    org_id: str
    handoff_email: str
    handoff_id: str


@dataclass
class UiWorld:
    """One pair of servers, and everything seeded into them."""

    api_base: str
    web_url: str
    checkout: CheckoutWorld
    admin: AdminWorld
    # Replace the API with one running a different environment (see
    # `restart_api` in the fixture). `None` puts the seeded environment back.
    restart_api: Callable[..., None]


def _create_administrator(api_env: dict[str, str], email: str) -> None:
    """Seed the first administrator the way the deployment does."""
    result = subprocess.run(  # noqa: S603 - fixed command, no shell
        [sys.executable, "create_admin.py", email, "--password-stdin"],
        cwd=str(BACKEND),
        env=api_env,
        input=f"{PASSWORD}\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"create_admin refused the seed account\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def _seed(
    api_base: str, web_url: str, api_env: dict[str, str]
) -> tuple[CheckoutWorld, AdminWorld]:
    """Make both journeys' accounts, restaurant, menu and application."""
    with httpx.Client(base_url=api_base, timeout=30.0) as client:
        owner = register(client, "restaurant_admin", "Kebab Corner Owner")
        owner_auth = {"Authorization": f"Bearer {owner['access_token']}"}

        restaurant = client.post(
            "/api/restaurants",
            json={
                "name": "Kebab Corner",
                "description": "The e2e kitchen",
                "cuisine_type": "turkish",
                "lat": 40.7,
                "lng": -74.0,
                "address": "1 Test St",
                "city": "NYC",
                "zip_code": "10001",
            },
            headers=owner_auth,
        )
        assert restaurant.status_code == 201, restaurant.text

        menu = client.put(
            f"/api/restaurants/{restaurant.json()['restaurant_id']}/menu",
            json=MENU,
            headers=owner_auth,
        )
        assert menu.status_code == 200, menu.text

        customer = register(client, "customer", "Casey Customer")

        # A car rather than a bike: the dropoff is ~1.5 km away, so the trip is
        # a few minutes and the board is not filtered out as too long.
        driver = register(client, "driver", "Casey Courier")
        signup = client.post(
            "/api/drivers/register",
            json={"vehicle_type": "car", "license_number": "E2E-1"},
            headers={"Authorization": f"Bearer {driver['access_token']}"},
        )
        assert signup.status_code == 201, signup.text

        # The admin journeys need an account to promote (Harper) and a pending
        # application to decide (Pat's food bank). A customer registration is
        # enough for both; the console promotions are what the journeys test.
        handoff = register(client, "customer", "Harper Handoff")
        admin_target = register(client, "driver", "Dana Driver")
        pantry_owner = register(client, "customer", "Pat Pantry")
        organization = client.post(
            "/api/organizations",
            json=ORGANIZATION,
            headers={"Authorization": f"Bearer {pantry_owner['access_token']}"},
        )
        assert organization.status_code == 201, organization.text

    admin_email = f"e2e-admin-{time.time_ns()}@example.com"
    _create_administrator(api_env, admin_email)

    return (
        CheckoutWorld(
            web_url=web_url,
            restaurant_id=restaurant.json()["restaurant_id"],
            item_id=MENU[0]["item_id"],
            customer=customer["email"],
            owner=owner["email"],
            driver=driver["email"],
        ),
        AdminWorld(
            api_base=api_base,
            web_url=web_url,
            admin_email=admin_email,
            user_id=admin_target["user"]["user_id"],
            org_id=organization.json()["org_id"],
            handoff_email=handoff["email"],
            handoff_id=handoff["user"]["user_id"],
        ),
    )


@pytest.fixture(scope="session")
def ui_world() -> Iterator[UiWorld]:
    """One backend and one frontend, seeded for both browser modules."""
    reason = skip_reason()
    if reason:
        pytest.skip(reason)

    workspace = Path(tempfile.mkdtemp(prefix="iftr-ui-e2e-"))
    api_port, web_port = free_port(), free_port()
    api_base = f"http://127.0.0.1:{api_port}"
    web_url = f"http://localhost:{web_port}"

    api_log = workspace / "api.log"
    web_log = workspace / "web.log"

    api_env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{(workspace / 'ui.db').as_posix()}",
        "UPLOADS_DIR": str(workspace / "uploads"),
        "UPLOADS_GC_LOG": str(workspace / "uploads_cleanup.log"),
        # Nothing here waits minutes for the sweep, and the tests must not race it.
        "UPLOADS_GC_INTERVAL_MINUTES": "0",
        "ENCRYPTION_KEY": os.environ.get("ENCRYPTION_KEY", "iftr-ui-e2e-encryption-key"),
        "LOG_LEVEL": "WARNING",
        # The dev server below is on a port picked moments ago, so it is not in
        # the app's default origin list.
        "FRONTEND_ORIGINS": f"{web_url},http://127.0.0.1:{web_port}",
    }
    web_env = {
        **os.environ,
        "BROWSER": "none",
        "CI": "false",
        "PORT": str(web_port),
        "HOST": "127.0.0.1",
        "GENERATE_SOURCEMAP": "false",
        "REACT_APP_BACKEND_URL": api_base,
    }

    def start_api(env: Dict[str, str]) -> subprocess.Popen:
        return spawn(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
                "--log-level",
                "warning",
            ],
            cwd=BACKEND,
            env=env,
            log=api_log,
        )

    # The process lives in a box rather than a local variable: a journey may
    # replace it (see `restart_api`), and the cleanup at the end has to stop
    # whichever one is current, not the one that started first.
    current = {"process": start_api(api_env)}

    def restart_api(overrides: Optional[Dict[str, str]] = None) -> None:
        """Replace the API with one running a different environment.

        Only the server's own settings change. The database stays where it is,
        the frontend keeps pointing at the same port, and a signed-in browser
        stays signed in - which is what makes it possible to show three
        configurations of one deployment without three compiles.

        `overrides` is merged over the environment the world was seeded with,
        and `None` means "back to that environment". A journey that changes it
        must put it back before it finishes: the other browser module shares
        this server. Each state names both Stripe variables explicitly, so a
        value the developer's shell exported cannot leak into a state that is
        supposed to have none.
        """
        stop(current["process"])
        env = api_env if overrides is None else {**api_env, **overrides}
        current["process"] = start_api(env)
        wait_for(f"{api_base}/openapi.json", 90, current["process"], api_log)

    web: Optional[subprocess.Popen] = None
    try:
        wait_for(f"{api_base}/openapi.json", 90, current["process"], api_log)
        checkout, admin = _seed(api_base, web_url, api_env)

        web = spawn(
            [shutil.which("npm") or "npm", "start"],
            cwd=FRONTEND,
            env=web_env,
            log=web_log,
        )
        # A cold CRA compile is the slow part of these tests; both modules use
        # this one, so it is paid once.
        wait_for(web_url, 300, web, web_log)

        yield UiWorld(
            api_base=api_base,
            web_url=web_url,
            checkout=checkout,
            admin=admin,
            restart_api=restart_api,
        )
    finally:
        if web is not None:
            stop(web)
        stop(current["process"])
        shutil.rmtree(workspace, ignore_errors=True)


def _restore_admin_world(api_base: str, world: AdminWorld) -> None:
    """Put the seeded accounts and application back where they started.

    The reset uses the same admin API the console does, so it is a real
    permission check and a no-op when nothing moved. It deliberately leaves the
    audit trail alone: the journeys assert against the newest entries for a
    subject, not against a globally empty history.
    """
    with httpx.Client(base_url=api_base, timeout=30.0) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": world.admin_email, "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        users = client.get("/api/admin/users", headers=headers)
        assert users.status_code == 200, users.text
        admin = next(
            (row for row in users.json() if row["email"] == world.admin_email),
            None,
        )
        assert admin is not None, "the seeded administrator is missing"

        for user_id, role in (
            (admin["user_id"], "admin"),
            (world.user_id, "driver"),
            (world.handoff_id, "customer"),
        ):
            response = client.put(
                f"/api/admin/users/{user_id}/role",
                json={"role": role},
                headers=headers,
            )
            assert response.status_code == 200, response.text

        # A journey may have ended between suspending an account and waking it
        # again. Reactivation is idempotent, so this is a no-op most of the time.
        for user_id in (admin["user_id"], world.user_id, world.handoff_id):
            response = client.put(
                f"/api/admin/users/{user_id}/active",
                json={"is_active": True},
                headers=headers,
            )
            assert response.status_code == 200, response.text

        organizations = client.get("/api/admin/organizations", headers=headers)
        assert organizations.status_code == 200, organizations.text
        organization = next(
            (
                row
                for row in organizations.json()
                if row["org_id"] == world.org_id
            ),
            None,
        )
        assert organization is not None, "the seeded organization is missing"
        if organization["is_verified"]:
            response = client.delete(
                f"/api/admin/organizations/{world.org_id}/verify",
                headers=headers,
            )
            assert response.status_code == 200, response.text


@pytest.fixture
def admin_world(ui_world) -> AdminWorld:
    """The shared world, reset to its seeded roles before each admin journey."""
    _restore_admin_world(ui_world.api_base, ui_world.admin)
    return ui_world.admin
