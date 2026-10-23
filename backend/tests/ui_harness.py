"""
The machinery the opt-in browser tests share.

Both journeys need the same things before a browser can be opened: a throwaway
uvicorn on a free port, a `craco start` dev server pointed at it, a way to sign
in through the form, and a clean shutdown that takes npm's node child with it.
They are here rather than in either test so a fix to the startup or the login
(``wait_for_url("**/dashboard")``) reaches both.

Only the browser tests import this, and only when they are enabled; nothing in
the ordinary suite starts a process or needs node.
"""

import os
import shutil
import time
from pathlib import Path
from typing import Dict, Optional

import httpx

# The process plumbing is shared with the crypto burn-in: one place that knows
# how to stop npm's node child and how to report a server that never came up.
from tests.processes import free_port, spawn, stop, tail, wait_for  # noqa: F401

# tests/ -> backend/ -> Evolved/ -> Evolved/frontend
BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"

PASSWORD = "passw0rd123"


def skip_reason() -> Optional[str]:
    """Why this run cannot drive a browser, or None when it can."""
    if os.getenv("RUN_UI_E2E") != "1":
        return "browser end-to-end test is opt-in: set RUN_UI_E2E=1"

    try:
        import playwright  # noqa: F401
    except ImportError:
        return "playwright is not installed: python -m pip install playwright"

    if shutil.which("npm") is None:
        return "npm is not on PATH"

    if not (FRONTEND / "node_modules").is_dir():
        return f"the frontend has no node_modules: npm install in {FRONTEND}"

    return None


def register(client: httpx.Client, role: str, name: str) -> Dict:
    """Register an account with a unique address; return the response body."""
    email = f"e2e-{role}-{time.time_ns()}@example.com"
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "name": name, "role": role},
    )
    assert response.status_code == 201, response.text
    return {**response.json(), "email": email}


def api_login(client: httpx.Client, email: str) -> Dict[str, str]:
    """Bearer headers for an already-seeded account, over the real API."""
    response = client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def register_driver_account(
    client: httpx.Client, name: str
) -> tuple[Dict, Dict[str, str]]:
    """An account signed up as a driver: (user, headers)."""
    account = register(client, "driver", name)
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    signup = client.post(
        "/api/drivers/register",
        json={"vehicle_type": "car", "license_number": f"E2E-{name}"},
        headers=headers,
    )
    assert signup.status_code == 201, signup.text
    return account, headers


def sign_in(browser, web_url: str, email: str):
    """A page signed in as `email`, through the form the user would use."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    # The first navigation pays for webpack's cold compile, which routinely
    # takes longer than twenty seconds on a laptop; the rest of the journey is
    # fast. This is a boot budget, not a licence for a stuck page to hang.
    page.set_default_timeout(45_000)

    page.goto(f"{web_url}/auth")
    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("password-input").fill(PASSWORD)
    page.get_by_test_id("submit-button").click()
    # The form signs in and only then leaves /auth; a failed login would stay.
    page.wait_for_url("**/dashboard")
    return page
