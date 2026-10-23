"""
One order placed, cooked and delivered through the browser.

The rest of the suite drives the API directly, so nothing in it can see the
screens: whether checkout sends the cart it drew, whether the kitchen's buttons
move the order it is showing, whether the driver's board offers what the kitchen
just finished, whether the tracker follows along. This test does, in the order a
real order travels:

    customer orders -> kitchen confirms, cooks, marks ready
    -> driver accepts, picks up, drives, completes -> customer sees "delivered"

What is real: a uvicorn process on a throwaway database, a `craco start` dev
server pointed at it, and Playwright clicking the buttons a customer, a cook and
a courier would click - login forms included. The accounts, restaurant and menu
are made over the API before the browser opens; the servers and seed are shared
with the admin journeys in `tests/ui_world.py`, so the CRA compile is paid once.

It is slow (a CRA compile, plus a browser) and needs node and a Playwright
browser, so it is opt-in rather than part of `pytest`:

    python -m playwright install chromium        # once per machine
    RUN_UI_E2E=1 pytest tests/test_e2e_checkout.py

Without RUN_UI_E2E the module skips, which keeps the ordinary suite at its usual
speed.
"""

import pytest

from tests.ui_harness import sign_in
from tests.ui_world import (
    DELIVERY_FEE,
    TIP,
    TOTAL,
    CheckoutWorld,
    ui_world,
)


@pytest.fixture(scope="module")
def stack(ui_world) -> CheckoutWorld:
    """The checkout world, on the stack both browser modules share."""
    return ui_world.checkout


# --------------------------------------------------------------------------
# The journey
# --------------------------------------------------------------------------


def test_a_customer_orders_the_kitchen_cooks_and_a_driver_delivers(stack: CheckoutWorld):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            # ----------------------------------------------------------------
            # The customer: pick a dish, say where it goes, place the order
            # ----------------------------------------------------------------
            customer = sign_in(browser, stack.web_url, stack.customer)

            customer.goto(f"{stack.web_url}/restaurants/{stack.restaurant_id}")
            customer.get_by_test_id(f"add-to-cart-{stack.item_id}").click()

            customer.get_by_test_id("view-cart-button").click()
            customer.get_by_test_id("checkout-button").click()

            customer.get_by_test_id("delivery-address-input").fill("9 Customer Rd")
            customer.get_by_test_id("delivery-option-leave_at_door").click()
            # The order summary is the number the tracker must agree with later.
            dialog = customer.get_by_role("dialog")
            expect(dialog.get_by_text(f"${TOTAL:.2f}")).to_be_visible()

            customer.get_by_test_id("place-order-button").click()

            # Placing an order lands on its tracker. This server has no Stripe
            # key, so the payment step answers 503; a checkout that treated
            # that as a failed order would strand the customer here - which is
            # what this waits on.
            customer.wait_for_url("**/orders/order_*")
            order_id = customer.url.rstrip("/").rsplit("/", 1)[-1]
            expect(
                customer.get_by_text("Waiting for restaurant confirmation")
            ).to_be_visible()
            expect(customer.get_by_text(f"${TOTAL:.2f}")).to_be_visible()

            # ----------------------------------------------------------------
            # The kitchen: confirm, cook, mark ready
            # ----------------------------------------------------------------
            kitchen = sign_in(browser, stack.web_url, stack.owner)
            kitchen.goto(f"{stack.web_url}/restaurant/orders")
            kitchen.get_by_role("tab", name="All").click()

            kitchen.get_by_role("button", name="Confirm", exact=True).click()
            kitchen.get_by_role("button", name="Start Preparing").click()
            kitchen.get_by_role("button", name="Mark Ready").click()
            expect(kitchen.get_by_text("Waiting for driver")).to_be_visible()

            # ----------------------------------------------------------------
            # The courier: accept, collect, drive, complete
            # ----------------------------------------------------------------
            courier = sign_in(browser, stack.web_url, stack.driver)
            courier.goto(f"{stack.web_url}/driver/deliveries")

            # What the board offers is the fee plus the tip, not the whole bill.
            expect(
                courier.get_by_test_id(f"pay-{order_id}")
            ).to_have_text(f"${DELIVERY_FEE + TIP:.2f}")

            courier.get_by_test_id(f"accept-order-{order_id}").click()
            courier.get_by_test_id("picked-up-button").click()
            courier.get_by_test_id("start-delivery-button").click()
            courier.get_by_test_id("complete-delivery-button").click()
            expect(
                courier.get_by_text("No orders available right now")
            ).to_be_visible()

            # ----------------------------------------------------------------
            # The customer again: the same order, finished
            # ----------------------------------------------------------------
            customer.reload()
            expect(
                customer.get_by_text("Order delivered! Enjoy your meal")
            ).to_be_visible()
            expect(customer.get_by_text(f"${TOTAL:.2f}")).to_be_visible()
        finally:
            browser.close()
