"""
Surplus runs worked from the volunteer's screen: one delivered, one returned.

The API suite proves the transitions, the counters and the ownership rules;
these journeys prove the driver can actually work them. A claimed run survives
a reload with both addresses, each button advances exactly one stage, completing
it takes the card off the screen and books the portions against the
organization, and abandoning an uncollected run puts it back on the board for
somebody else.

The restaurant, listing, verified organization and reservation are made over
the API first, the same split the other journeys use: registering a food bank by
hand is a different test. The browser opens on the volunteer's own screen.

It shares the throwaway servers and seed in `tests/ui_world.py`, so the CRA
compile is paid once for all three browser modules. Like the others it is
opt-in:

    python -m playwright install chromium        # once per machine
    RUN_UI_E2E=1 pytest tests/test_e2e_surplus.py
"""

import time

import httpx
import pytest

from tests.ui_harness import (
    api_login,
    register,
    register_driver_account,
    sign_in,
)
from tests.ui_world import UiWorld, ui_world


@pytest.fixture(scope="module")
def stack(ui_world) -> UiWorld:
    """The shared stack; each journey seeds the rows it needs."""
    return ui_world


def seed_claimed_run(
    api: httpx.Client,
    stack: UiWorld,
    org_name: str,
    volunteer_name: str,
):
    """A verified food bank, a listing, a reservation, and a claimed run.

    Returns (org_id, org_headers, delivery_id, volunteer account, driver
    headers). Everything is new per call, so the two journeys do not share a
    run or a counter.
    """
    admin_headers = api_login(api, stack.admin.admin_email)

    org_owner = register(api, "organization_admin", f"{org_name} Owner")
    org_headers = {"Authorization": f"Bearer {org_owner['access_token']}"}
    organization = api.post(
        "/api/organizations",
        json={
            "name": org_name,
            "description": "A neighborhood pantry",
            "org_type": "food_bank",
            "lat": 40.71,
            "lng": -74.0,
            "address": "12 Market St",
            "city": "Newark",
            "contact_email": f"hello-{time.time_ns()}@example.org",
            "contact_phone": "555-0143",
        },
        headers=org_headers,
    )
    assert organization.status_code == 201, organization.text
    org_id = organization.json()["org_id"]

    verified = api.put(
        f"/api/admin/organizations/{org_id}/verify", headers=admin_headers
    )
    assert verified.status_code == 200, verified.text

    owner_headers = api_login(api, stack.checkout.owner)
    listed = api.post(
        "/api/surplus",
        json={
            "description": "Two trays of lasagna",
            "quantity": 3,
            "original_price": 30.0,
        },
        headers=owner_headers,
    )
    assert listed.status_code == 201, listed.text
    surplus_id = listed.json()["surplus_id"]

    reserved = api.post(
        f"/api/surplus/{surplus_id}/reserve",
        json={"quantity": 2},
        headers=org_headers,
    )
    assert reserved.status_code == 200, reserved.text
    delivery_id = reserved.json()["delivery_id"]

    volunteer, volunteer_headers = register_driver_account(api, volunteer_name)
    claimed = api.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=volunteer_headers,
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["status"] == "assigned"

    return org_id, org_headers, delivery_id, volunteer, volunteer_headers


def test_a_volunteer_collects_and_delivers_a_surplus_run(stack: UiWorld):
    from playwright.sync_api import expect, sync_playwright

    with httpx.Client(base_url=stack.api_base, timeout=30.0) as api:
        org_id, org_headers, delivery_id, volunteer, _ = seed_claimed_run(
            api, stack, "Harbor Pantry E2E", "Vera Volunteer"
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, volunteer["email"])
            page.goto(f"{stack.web_url}/driver/deliveries")

            run = page.get_by_test_id(f"active-surplus-{delivery_id}")
            expect(run).to_be_visible()
            expect(run).to_contain_text("Harbor Pantry E2E")
            expect(run).to_contain_text("2 portions")
            expect(run).to_contain_text("1 Test St")
            expect(run).to_contain_text("12 Market St")

            run.get_by_test_id(f"surplus-picked-up-{delivery_id}").click()
            expect(
                page.get_by_text("Surplus run marked as picked up")
            ).to_be_visible()

            page.get_by_test_id(f"surplus-start-delivery-{delivery_id}").click()
            expect(
                page.get_by_text("Surplus run marked as in transit")
            ).to_be_visible()

            page.get_by_test_id(f"surplus-complete-delivery-{delivery_id}").click()
            expect(
                page.get_by_text("Surplus delivered! 2 portions received.")
            ).to_be_visible()
            expect(
                page.get_by_test_id(f"active-surplus-{delivery_id}")
            ).to_have_count(0)
        finally:
            browser.close()

    with httpx.Client(base_url=stack.api_base, timeout=30.0) as api:
        organization = api.get(f"/api/organizations/{org_id}", headers=org_headers)
        assert organization.status_code == 200, organization.text
        assert organization.json()["total_received"] == 2

        reservations = api.get("/api/surplus/reservations", headers=org_headers)
        assert reservations.status_code == 200, reservations.text
        row = next(
            entry
            for entry in reservations.json()
            if entry["delivery_id"] == delivery_id
        )
        assert row["delivery_status"] == "delivered"


def test_a_volunteer_returns_an_uncollected_run_to_the_pool(stack: UiWorld):
    from playwright.sync_api import expect, sync_playwright

    with httpx.Client(base_url=stack.api_base, timeout=30.0) as api:
        org_id, org_headers, delivery_id, volunteer, _ = seed_claimed_run(
            api, stack, "Second Chance Pantry", "Avery Abandon"
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, volunteer["email"])
            page.goto(f"{stack.web_url}/driver/deliveries")

            expect(
                page.get_by_test_id(f"active-surplus-{delivery_id}")
            ).to_be_visible()
            page.get_by_test_id(f"surplus-abandon-{delivery_id}").click()

            dialog = page.get_by_role("alertdialog")
            expect(dialog).to_contain_text("Return this run to the pool?")
            page.get_by_test_id(
                f"confirm-surplus-abandon-{delivery_id}"
            ).click()

            expect(
                page.get_by_text("Run returned to the volunteer pool")
            ).to_be_visible()
            expect(
                page.get_by_test_id(f"active-surplus-{delivery_id}")
            ).to_have_count(0)
        finally:
            browser.close()

    with httpx.Client(base_url=stack.api_base, timeout=30.0) as api:
        # It is back on the board and still the organization's reservation.
        _, other_headers = register_driver_account(api, "Noah Next")
        board = api.get("/api/drivers/surplus-deliveries", headers=other_headers)
        assert board.status_code == 200, board.text
        assert delivery_id in {row["delivery_id"] for row in board.json()}

        reservations = api.get("/api/surplus/reservations", headers=org_headers)
        assert reservations.status_code == 200, reservations.text
        row = next(
            entry
            for entry in reservations.json()
            if entry["delivery_id"] == delivery_id
        )
        assert row["delivery_status"] == "pending"

        organization = api.get(f"/api/organizations/{org_id}", headers=org_headers)
        assert organization.status_code == 200, organization.text
        assert organization.json()["total_received"] == 0
