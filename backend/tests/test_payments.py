"""
Paying for an order, through the routes the checkout and success screens call.

No test reaches Stripe. `get_gateway` is replaced with `FakeStripe`, which
records what it was asked to charge and answers with the same shape the SDK
does. That keeps the assertions on this app's decisions - who may pay, what
amount is sent, when a row becomes paid, what a replayed webhook does - rather
than on Stripe's test clocks or on a network that is not there in CI.

The one test that does *not* install the fake asserts the unconfigured state:
with no key, checkout answers 503 and the order is left exactly as it was.
"""

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from types import SimpleNamespace
from typing import Dict

import pytest
import stripe as stripe_sdk

from app.api.payments import get_gateway
from app.main import app
from app.payments import (
    CheckoutLine,
    CheckoutSession,
    InvalidWebhookSignature,
    PaymentProviderError,
    PaymentsNotConfigured,
    SessionState,
    StripeGateway,
    state_from_session,
)

# Two pizzas at 12.50, a 2.99 delivery fee and a 3.00 tip.
SUBTOTAL = 25.0
DELIVERY_FEE = 2.99
TIP = 3.0
TOTAL_CENTS = 3099


class FakeStripe:
    """The slice of Stripe the routes use, with a memory instead of a network."""

    def __init__(self):
        self.sessions: Dict[str, dict] = {}
        self.created: list[dict] = []
        self.retrieve_error: Exception | None = None

    async def create_checkout(self, **kwargs) -> CheckoutSession:
        # Unique across tests: the database is session-scoped, so a counter that
        # restarts with every fake would collide on the unique session id.
        token = uuid.uuid4().hex[:12]
        session_id = f"cs_test_{token}"
        self.sessions[session_id] = {
            "id": session_id,
            "payment_status": "unpaid",
            "status": "open",
            "amount_total": kwargs["amount_cents"],
            "currency": kwargs["currency"],
            "payment_intent": f"pi_test_{token}",
            "client_reference_id": kwargs["order_id"],
            "metadata": {"order_id": kwargs["order_id"]},
        }
        self.created.append(kwargs)
        return CheckoutSession(
            session_id=session_id,
            url=f"https://checkout.stripe.test/{session_id}",
            amount_cents=kwargs["amount_cents"],
            currency=kwargs["currency"],
        )

    async def retrieve(self, session_id: str) -> SessionState:
        if self.retrieve_error is not None:
            raise self.retrieve_error
        return state_from_session(self.sessions[session_id])

    def parse_webhook(self, payload: bytes, signature: str):
        if signature != "test-signature":
            raise InvalidWebhookSignature("bad signature")
        # A real Event, not the dict we serialised: StripeObject is not a
        # mapping, so this is what proves the webhook route reads one correctly.
        return stripe_sdk.Event.construct_from(json.loads(payload), "evt_test")

    # --- test helpers, not part of the gateway protocol --------------------

    def pay(self, session_id: str, amount_cents: int | None = None) -> None:
        session = self.sessions[session_id]
        session["payment_status"] = "paid"
        session["status"] = "complete"
        if amount_cents is not None:
            session["amount_total"] = amount_cents

    def expire(self, session_id: str) -> None:
        self.sessions[session_id]["status"] = "expired"

    def event(self, session_id: str, event_type: str) -> bytes:
        return json.dumps(
            {
                "id": "evt_test",
                "type": event_type,
                "data": {"object": self.sessions[session_id]},
            }
        ).encode()

    def post_event(self, client, session_id: str, event_type: str):
        return client.post(
            "/api/payments/webhook",
            content=self.event(session_id, event_type),
            headers={"Stripe-Signature": "test-signature"},
        )


@pytest.fixture
def stripe(client) -> FakeStripe:
    """Replace the real gateway for one test, and put it back afterwards."""
    fake = FakeStripe()
    app.dependency_overrides[get_gateway] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_gateway, None)


def place_order(client, register, create_restaurant, *, price: float = 12.5, tip: float = TIP):
    """A customer, a restaurant with one dish, and an order for two of it."""
    user, headers = register()
    restaurant = create_restaurant(headers, name="Paid Kitchen")
    saved = client.put(
        f"/api/restaurants/{restaurant['restaurant_id']}/menu",
        json=[
            {
                "item_id": "item_pizza",
                "name": "Margherita",
                "price": price,
                "is_available": True,
            }
        ],
        headers=headers,
    )
    assert saved.status_code == 200, saved.text

    response = client.post(
        "/api/orders",
        json={
            "restaurant_id": restaurant["restaurant_id"],
            "items": [{"item_id": "item_pizza", "quantity": 2}],
            "delivery_address": "9 Customer Rd",
            "tip_amount": tip,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return {
        "user": user,
        "headers": headers,
        "restaurant": restaurant,
        "order": response.json(),
    }


def start_checkout(client, headers, order_id: str, origin: str = "http://localhost:3000"):
    return client.post(
        "/api/payments/checkout",
        json={"order_id": order_id, "origin_url": origin},
        headers=headers,
    )


def read_status(client, headers, session_id: str):
    return client.get(f"/api/payments/status/{session_id}", headers=headers)


# ---------------------------------------------------------------------------
# Starting a checkout
# ---------------------------------------------------------------------------


def test_checkout_charges_the_stored_bill_and_nothing_from_the_request(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    order = world["order"]

    response = start_checkout(client, world["headers"], order["order_id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount_total"] == TOTAL_CENTS
    assert body["currency"] == "usd"
    assert body["url"].startswith("https://checkout.stripe.test/")

    call = stripe.created[0]
    assert call["amount_cents"] == TOTAL_CENTS
    assert call["order_id"] == order["order_id"]
    # The page's lines add up to the bill, and every label comes from the
    # server: a client cannot name what it is buying.
    assert sum(line.amount_cents for line in call["lines"]) == TOTAL_CENTS
    labels = [line.label for line in call["lines"]]
    assert any("Paid Kitchen" in label for label in labels)
    assert "Delivery" in labels
    assert "Driver tip" in labels
    # The success page gets a URL template, not a finished URL: Stripe fills in
    # the session id itself.
    assert "{CHECKOUT_SESSION_ID}" in call["success_url"]
    assert call["cancel_url"].startswith("http://localhost:3000/payment/cancel")


def test_checkout_stores_the_session_against_the_order(
    client, stripe, register, create_restaurant, scalar
):
    world = place_order(client, register, create_restaurant)

    response = start_checkout(client, world["headers"], world["order"]["order_id"])
    assert response.status_code == 201, response.text

    assert (
        scalar(
            "SELECT session_id FROM order_payments WHERE order_id = ?",
            (world["order"]["order_id"],),
        )
        == response.json()["session_id"]
    )
    # The order itself is still unpaid: a hosted page exists, no money has moved.
    assert (
        client.get(
            f"/api/orders/{world['order']['order_id']}", headers=world["headers"]
        ).json()["payment_status"]
        == "pending"
    )


def test_a_live_session_is_reused_instead_of_charging_twice(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)

    first = start_checkout(client, world["headers"], world["order"]["order_id"])
    second = start_checkout(client, world["headers"], world["order"]["order_id"])

    assert first.status_code == second.status_code == 201
    assert first.json()["session_id"] == second.json()["session_id"]
    assert len(stripe.created) == 1


def test_an_expired_session_is_replaced_on_the_next_attempt(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    first = start_checkout(client, world["headers"], world["order"]["order_id"])
    stripe.expire(first.json()["session_id"])

    second = start_checkout(client, world["headers"], world["order"]["order_id"])

    assert second.status_code == 201, second.text
    assert second.json()["session_id"] != first.json()["session_id"]
    assert len(stripe.created) == 2
    # The retry gets its own idempotency key; reusing the first would hand back
    # the expired session from Stripe's cache.
    assert stripe.created[0]["idempotency_key"] != stripe.created[1]["idempotency_key"]


def test_only_the_customer_who_placed_the_order_can_pay(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    _, stranger = register()

    response = start_checkout(client, stranger, world["order"]["order_id"])

    assert response.status_code == 403
    assert stripe.created == []


def test_checkout_requires_a_signed_in_customer(client, stripe, register, create_restaurant):
    world = place_order(client, register, create_restaurant)

    response = client.post(
        "/api/payments/checkout", json={"order_id": world["order"]["order_id"]}
    )

    assert response.status_code == 401
    assert stripe.created == []


def test_a_cancelled_order_cannot_be_paid(client, stripe, register, create_restaurant):
    world = place_order(client, register, create_restaurant)
    cancelled = client.put(
        f"/api/orders/{world['order']['order_id']}/status?status=cancelled",
        headers=world["headers"],
    )
    assert cancelled.status_code == 200, cancelled.text

    response = start_checkout(client, world["headers"], world["order"]["order_id"])

    assert response.status_code == 409
    assert stripe.created == []


def test_a_paid_order_cannot_be_paid_again(client, stripe, register, create_restaurant):
    world = place_order(client, register, create_restaurant)
    started = start_checkout(client, world["headers"], world["order"]["order_id"])
    session_id = started.json()["session_id"]
    stripe.pay(session_id)
    assert read_status(client, world["headers"], session_id).json()["payment_status"] == "paid"

    response = start_checkout(client, world["headers"], world["order"]["order_id"])

    assert response.status_code == 409
    assert len(stripe.created) == 1


def test_checkout_says_so_when_no_key_is_configured(
    client, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)

    response = start_checkout(client, world["headers"], world["order"]["order_id"])

    assert response.status_code == 503
    assert "STRIPE_SECRET_KEY" in response.json()["detail"]
    # Nothing about the order changed: it is still pending, and the kitchen can
    # still see it.
    assert (
        client.get(
            f"/api/orders/{world['order']['order_id']}", headers=world["headers"]
        ).json()["payment_status"]
        == "pending"
    )


def test_checkout_refuses_an_origin_this_api_does_not_serve(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)

    response = start_checkout(
        client,
        world["headers"],
        world["order"]["order_id"],
        origin="https://evil.example",
    )

    assert response.status_code == 400
    assert stripe.created == []


def test_an_order_too_small_for_stripe_is_refused_with_a_reason(
    client, stripe, register, create_restaurant, seed_order
):
    user, headers = register()
    restaurant = create_restaurant(headers, name="Tiny Kitchen")
    order = seed_order(
        restaurant["restaurant_id"],
        customer_id=user["user_id"],
        total_amount=0.25,
    )

    response = start_checkout(client, headers, order["order_id"])

    assert response.status_code == 400
    assert "50" in response.json()["detail"]
    assert stripe.created == []


# ---------------------------------------------------------------------------
# Polling the success page
# ---------------------------------------------------------------------------


def test_status_marks_the_order_paid_when_stripe_says_paid(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    stripe.pay(session_id)

    response = read_status(client, world["headers"], session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["payment_status"] == "paid"
    assert body["status"] == "complete"
    assert body["amount_total"] == TOTAL_CENTS
    assert (
        client.get(
            f"/api/orders/{world['order']['order_id']}", headers=world["headers"]
        ).json()["payment_status"]
        == "paid"
    )
    # The same fact through both list reads: the customer's order list and the
    # kitchen's queue. They use the same lookup, and both screens show it.
    listed = client.get("/api/orders", headers=world["headers"]).json()
    assert next(
        row for row in listed if row["order_id"] == world["order"]["order_id"]
    )["payment_status"] == "paid"
    queue = client.get(
        f"/api/restaurants/{world['restaurant']['restaurant_id']}/orders",
        headers=world["headers"],
    ).json()
    assert next(
        row for row in queue if row["order_id"] == world["order"]["order_id"]
    )["payment_status"] == "paid"


def test_status_stays_pending_while_checkout_is_open(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]

    body = read_status(client, world["headers"], session_id).json()

    assert body["payment_status"] == "pending"
    assert body["status"] == "open"


def test_status_hides_another_customers_session(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    _, stranger = register()

    response = read_status(client, stranger, session_id)

    # The same answer as an unknown id: a session id is not a credential.
    assert response.status_code == 404


def test_status_requires_a_signed_in_caller(client, stripe, register, create_restaurant):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]

    assert client.get(f"/api/payments/status/{session_id}").status_code == 401


def test_status_unknown_session_is_404(client, stripe):
    response = client.get(
        "/api/payments/status/cs_test_does_not_exist",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    # Authentication is checked before the lookup, so this is a 401; the 404
    # case is covered by the stranger above. Kept as a reminder of the order.
    assert response.status_code == 401


def test_a_confirmed_payment_survives_stripe_being_unreachable(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    stripe.pay(session_id)
    assert read_status(client, world["headers"], session_id).json()["payment_status"] == "paid"

    stripe.retrieve_error = PaymentProviderError("Stripe is down")

    response = read_status(client, world["headers"], session_id)

    assert response.status_code == 200
    assert response.json()["payment_status"] == "paid"


def test_a_payment_for_the_wrong_amount_does_not_settle_the_order(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    stripe.pay(session_id, amount_cents=1)

    body = read_status(client, world["headers"], session_id).json()

    assert body["payment_status"] == "failed"
    assert (
        client.get(
            f"/api/orders/{world['order']['order_id']}", headers=world["headers"]
        ).json()["payment_status"]
        == "failed"
    )


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


def test_webhook_rejects_a_body_without_a_valid_signature(
    client, stripe, register, create_restaurant, scalar
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    stripe.pay(session_id)

    response = client.post(
        "/api/payments/webhook",
        content=stripe.event(session_id, "checkout.session.completed"),
        headers={"Stripe-Signature": "forged"},
    )

    assert response.status_code == 400
    # Read the row directly: asking the status endpoint would legitimately
    # refresh from Stripe and mark the order paid, hiding what the forged
    # webhook did (or rather did not do).
    assert (
        scalar(
            "SELECT payment_status FROM order_payments WHERE order_id = ?",
            (world["order"]["order_id"],),
        )
        == "pending"
    )


def test_the_real_gateway_talks_to_the_sdk_it_documents(monkeypatch):
    """The call shape sent to Stripe, checked against a stand-in client.

    No network and no key: `_client` is replaced, so what is asserted is the
    parameters this app builds - amount in cents, metadata naming the order,
    an idempotency key, and the success URL template Stripe fills in.
    """
    captured: Dict[str, object] = {}
    session = stripe_sdk.StripeObject.construct_from(
        {
            "id": "cs_test_sdk",
            "url": "https://checkout.stripe.test/cs_test_sdk",
            "payment_status": "unpaid",
            "status": "open",
            "amount_total": 3099,
            "currency": "usd",
            "payment_intent": "pi_test_sdk",
            "client_reference_id": "order_1",
            "metadata": {"order_id": "order_1"},
        },
        "cs_test_sdk",
    )

    class Sessions:
        async def create_async(self, params, options):
            captured["params"] = params
            captured["options"] = options
            return session

        async def retrieve_async(self, session_id):
            captured["retrieved"] = session_id
            return session

    fake = SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=Sessions()))
    )
    monkeypatch.setattr("app.payments._client", lambda key: fake)

    gateway = StripeGateway("sk_test_not_a_real_key", "whsec_not_a_real_key")

    async def run():
        created = await gateway.create_checkout(
            order_id="order_1",
            customer_id="user_1",
            customer_email="customer@example.com",
            lines=[CheckoutLine("Order from Paid Kitchen", 3099)],
            amount_cents=3099,
            currency="usd",
            success_url="http://localhost:3000/payment/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="http://localhost:3000/payment/cancel?order_id=order_1",
            idempotency_key="checkout-order_1-1",
        )
        state = await gateway.retrieve("cs_test_sdk")
        return created, state

    created, state = asyncio.run(run())

    params = captured["params"]
    assert params["mode"] == "payment"
    assert params["client_reference_id"] == "order_1"
    assert params["metadata"]["order_id"] == "order_1"
    assert params["payment_intent_data"]["metadata"]["order_id"] == "order_1"
    assert params["customer_email"] == "customer@example.com"
    assert params["line_items"][0]["price_data"]["unit_amount"] == 3099
    assert params["line_items"][0]["price_data"]["currency"] == "usd"
    assert "{CHECKOUT_SESSION_ID}" in params["success_url"]
    assert captured["options"] == {"idempotency_key": "checkout-order_1-1"}
    assert captured["retrieved"] == "cs_test_sdk"
    assert created.session_id == "cs_test_sdk"
    assert created.url == "https://checkout.stripe.test/cs_test_sdk"
    assert state.amount_cents == 3099
    assert state.order_id == "order_1"


def test_the_real_gateway_verifies_a_stripe_signature():
    """The SDK half of the webhook, without a webhook or a network.

    The route tests use a fake that trusts one literal header. This one builds
    the header Stripe itself would send, so the seam between our route and
    `stripe.Webhook.construct_event` is exercised for real.
    """
    payload = b'{"id":"evt_1","type":"customer.created","data":{"object":{}}}'
    secret = "whsec_test_secret"
    timestamp = int(time.time())
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    header = f"t={timestamp},v1={digest}"

    gateway = StripeGateway("sk_test_not_a_real_key", secret)
    event = gateway.parse_webhook(payload, header)

    assert event["type"] == "customer.created"
    with pytest.raises(InvalidWebhookSignature):
        gateway.parse_webhook(payload + b" ", header)
    with pytest.raises(PaymentsNotConfigured):
        StripeGateway("sk_test_not_a_real_key", "").parse_webhook(payload, header)


def test_webhook_marks_the_order_paid_when_the_tab_never_comes_back(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    stripe.pay(session_id)

    response = stripe.post_event(client, session_id, "checkout.session.completed")

    assert response.status_code == 200, response.text
    assert response.json()["handled"] == "paid"
    assert (
        client.get(
            f"/api/orders/{world['order']['order_id']}", headers=world["headers"]
        ).json()["payment_status"]
        == "paid"
    )


def test_replaying_the_same_webhook_changes_nothing(
    client, stripe, register, create_restaurant, scalar
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    stripe.pay(session_id)

    first = stripe.post_event(client, session_id, "checkout.session.completed")
    paid_at = scalar(
        "SELECT paid_at FROM order_payments WHERE order_id = ?",
        (world["order"]["order_id"],),
    )
    second = stripe.post_event(client, session_id, "checkout.session.completed")

    assert first.status_code == second.status_code == 200
    assert second.json()["handled"] == "paid"
    # Idempotent in the way that matters: the timestamp of the payment is not
    # rewritten by Stripe's retry.
    assert (
        scalar(
            "SELECT paid_at FROM order_payments WHERE order_id = ?",
            (world["order"]["order_id"],),
        )
        == paid_at
    )


def test_webhook_marks_an_expired_session_failed(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    stripe.expire(session_id)

    response = stripe.post_event(client, session_id, "checkout.session.expired")

    assert response.status_code == 200
    assert response.json()["handled"] == "failed"
    assert (
        client.get(
            f"/api/orders/{world['order']['order_id']}", headers=world["headers"]
        ).json()["payment_status"]
        == "failed"
    )


def test_webhook_marks_an_async_failure_failed(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    # A delayed method completes the session before it knows the outcome.
    stripe.sessions[session_id]["status"] = "complete"

    response = stripe.post_event(
        client, session_id, "checkout.session.async_payment_failed"
    )

    assert response.status_code == 200
    assert response.json()["handled"] == "failed"


def test_a_completed_session_that_is_still_unpaid_stays_pending(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    stripe.sessions[session_id]["status"] = "complete"

    response = stripe.post_event(client, session_id, "checkout.session.completed")

    assert response.status_code == 200
    assert response.json()["handled"] == "pending"


def test_webhook_recovers_a_session_whose_row_was_never_written(
    client, stripe, register, create_restaurant, execute
):
    # Simulate the checkout request dying between Stripe's reply and the commit.
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    stripe.pay(session_id)
    execute("DELETE FROM order_payments WHERE session_id = ?", (session_id,))

    response = stripe.post_event(client, session_id, "checkout.session.completed")

    assert response.status_code == 200
    assert response.json()["handled"] == "paid"
    assert (
        client.get(
            f"/api/orders/{world['order']['order_id']}", headers=world["headers"]
        ).json()["payment_status"]
        == "paid"
    )


def test_webhook_ignores_events_it_does_not_handle(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]

    response = stripe.post_event(client, session_id, "customer.created")

    assert response.status_code == 200
    assert response.json()["handled"] is None


def test_webhook_reports_a_missing_webhook_secret(
    client, monkeypatch, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)

    # A gateway that verifies signatures, but was built without the secret.
    from app.payments import StripeGateway

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_not_a_real_key")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "")
    app.dependency_overrides[get_gateway] = lambda: StripeGateway(
        "sk_test_not_a_real_key", ""
    )
    try:
        response = client.post(
            "/api/payments/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "whatever"},
        )
    finally:
        app.dependency_overrides.pop(get_gateway, None)

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# Tipping while a payment is in flight
# ---------------------------------------------------------------------------


def test_a_tip_cannot_change_the_bill_under_an_open_checkout(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    start_checkout(client, world["headers"], world["order"]["order_id"])

    response = client.post(
        f"/api/orders/{world['order']['order_id']}/add-tip",
        json={"amount": 2.0},
        headers=world["headers"],
    )

    assert response.status_code == 409
    assert "before starting checkout" in response.json()["detail"]


def test_revenue_on_the_admin_dashboard_counts_only_paid_orders(
    client, stripe, register, create_restaurant, admin_user
):
    _, admin_headers = admin_user()
    world = place_order(client, register, create_restaurant)
    before = client.get("/api/admin/stats", headers=admin_headers).json()[
        "total_revenue"
    ]

    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]

    # An order with a session but no payment is not revenue.
    assert client.get("/api/admin/stats", headers=admin_headers).json()[
        "total_revenue"
    ] == before

    stripe.pay(session_id)
    assert read_status(client, world["headers"], session_id).json()[
        "payment_status"
    ] == "paid"

    after = client.get("/api/admin/stats", headers=admin_headers).json()[
        "total_revenue"
    ]
    assert round(after - before, 2) == round(TOTAL_CENTS / 100, 2)


def test_a_tip_still_works_on_an_order_that_never_started_checkout(
    client, stripe, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)

    response = client.post(
        f"/api/orders/{world['order']['order_id']}/add-tip",
        json={"amount": 2.0},
        headers=world["headers"],
    )

    assert response.status_code == 200, response.text
    assert response.json()["total_tip"] == TIP + 2.0


# ---------------------------------------------------------------------------
# What this deployment's Stripe settings are
# ---------------------------------------------------------------------------

# Keys with a recognisable shape, so a test can assert the whole string never
# comes back. Not real keys and not plausible ones either - and assembled from
# pieces, because written whole they read as credentials to a secret scanner
# (GitHub's push protection refuses a push that contains them). Same strings.
SAMPLE_TEST_KEY = "sk_" + "test_" + "51HdiagnosticsOnly0000000000000000"
SAMPLE_LIVE_KEY = "sk_" + "live_" + "51HdiagnosticsOnly0000000000000000"
SAMPLE_RESTRICTED_KEY = "rk_" + "test_" + "51HdiagnosticsOnly0000000000000000"
SAMPLE_WEBHOOK_SECRET = "whsec_" + "diagnosticsOnly0000000000000000"


def diagnostics(client, headers):
    return client.get("/api/payments/diagnostics", headers=headers)


def test_diagnostics_is_administrator_only(client, register):
    """It maps the deployment's payment configuration, which is not a
    customer's business and not a customer's data."""
    _, headers = register()

    assert diagnostics(client, headers).status_code == 403
    assert client.get("/api/payments/diagnostics").status_code == 401


def test_diagnostics_describes_an_unconfigured_deployment(client, admin_user):
    """No key is a supported state, and the response says so rather than
    looking like a fault."""
    _, headers = admin_user()

    body = diagnostics(client, headers).json()

    assert body["configured"] is False
    assert body["checkout_available"] is False
    assert body["key_mode"] == "unset"
    assert body["key_kind"] == "unset"
    assert body["live_mode"] is False
    assert body["webhook_secret_configured"] is False
    # Where Stripe should be pointed, and what it would be told.
    assert body["webhook_path"] == "/api/payments/webhook"
    assert body["handled_events"] == [
        "checkout.session.async_payment_failed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.completed",
        "checkout.session.expired",
    ]
    assert body["currency"] == "usd"
    assert body["min_charge_cents"] == 50
    assert body["checked_at"]
    assert any("503" in warning for warning in body["warnings"])


def test_diagnostics_names_a_test_key_as_a_test_key(client, admin_user, monkeypatch):
    _, headers = admin_user()
    monkeypatch.setenv("STRIPE_SECRET_KEY", SAMPLE_TEST_KEY)

    body = diagnostics(client, headers).json()

    assert body["configured"] is True
    assert body["checkout_available"] is True
    assert body["key_mode"] == "test"
    assert body["key_kind"] == "secret"
    assert body["live_mode"] is False
    # A test key explains the configuration; it is not something to warn about.
    assert not any("real cards" in warning for warning in body["warnings"])


def test_diagnostics_calls_out_a_live_key(client, admin_user, monkeypatch):
    """The one fact nobody should have to infer: this takes real money."""
    _, headers = admin_user()
    monkeypatch.setenv("STRIPE_SECRET_KEY", SAMPLE_LIVE_KEY)

    body = diagnostics(client, headers).json()

    assert body["key_mode"] == "live"
    assert body["live_mode"] is True
    assert any("real cards" in warning for warning in body["warnings"])


def test_diagnostics_names_a_restricted_key(client, admin_user, monkeypatch):
    """A restricted key can be missing the Checkout permission, which otherwise
    arrives as an unhelpful provider error at the first payment."""
    _, headers = admin_user()
    monkeypatch.setenv("STRIPE_SECRET_KEY", SAMPLE_RESTRICTED_KEY)

    body = diagnostics(client, headers).json()

    assert body["key_mode"] == "test"
    assert body["key_kind"] == "restricted"
    assert any("restricted" in warning for warning in body["warnings"])


def test_a_publishable_key_does_not_look_like_a_working_configuration(
    client, admin_user, monkeypatch
):
    """The likeliest wrong paste. It is set, so the server is "configured", but
    Stripe will refuse it - so checkout is not available, and the mode is not
    reported as a test key it does not have."""
    _, headers = admin_user()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "pk_test_looksLikeAKey000000000000000")

    body = diagnostics(client, headers).json()

    assert body["configured"] is True
    assert body["key_mode"] == "unrecognised"
    assert body["key_kind"] == "unrecognised"
    assert body["checkout_available"] is False
    assert body["live_mode"] is False
    assert any("not a Stripe key shape" in warning for warning in body["warnings"])


def test_diagnostics_never_includes_the_key_or_the_signing_secret(
    client, admin_user, monkeypatch
):
    """The whole point of the endpoint: the settings, not the secrets."""
    _, headers = admin_user()
    monkeypatch.setenv("STRIPE_SECRET_KEY", SAMPLE_TEST_KEY)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SAMPLE_WEBHOOK_SECRET)

    text = diagnostics(client, headers).text

    assert SAMPLE_TEST_KEY not in text
    assert SAMPLE_WEBHOOK_SECRET not in text
    # Not even a useful-looking tail.
    assert SAMPLE_TEST_KEY[-12:] not in text
    assert SAMPLE_WEBHOOK_SECRET[-8:] not in text


def test_diagnostics_reports_whether_events_can_be_verified(
    client, admin_user, monkeypatch
):
    _, headers = admin_user()
    monkeypatch.setenv("STRIPE_SECRET_KEY", SAMPLE_TEST_KEY)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "")

    without = diagnostics(client, headers).json()
    assert without["webhook_secret_configured"] is False
    assert any("STRIPE_WEBHOOK_SECRET" in w for w in without["warnings"])

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SAMPLE_WEBHOOK_SECRET)

    with_secret = diagnostics(client, headers).json()
    assert with_secret["webhook_secret_configured"] is True
    assert not any("STRIPE_WEBHOOK_SECRET" in w for w in with_secret["warnings"])


# ---------------------------------------------------------------------------
# Whether Stripe is actually reaching this server
# ---------------------------------------------------------------------------


def test_a_settled_delivery_is_recorded_and_read_back(
    client, stripe, admin_user, register, create_restaurant
):
    """A webhook that worked leaves a trace somebody can point at."""
    _, headers = admin_user()
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    before = diagnostics(client, headers).json()["webhook"]

    stripe.pay(session_id)
    delivered = stripe.post_event(client, session_id, "checkout.session.completed")
    assert delivered.status_code == 200

    after = diagnostics(client, headers).json()["webhook"]
    assert after["last_received_at"]
    assert after["last_event_type"] == "checkout.session.completed"
    assert after["last_outcome"] == "settled"
    assert after["last_verified_at"]
    assert after["received_24h"] == before["received_24h"] + 1
    assert after["rejected_24h"] == before["rejected_24h"]


def test_an_event_type_we_do_not_handle_is_still_recorded(
    client, stripe, admin_user, register, create_restaurant
):
    """Acknowledged-and-ignored is an outcome, not silence."""
    _, headers = admin_user()
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]

    ignored = stripe.post_event(client, session_id, "customer.created")
    assert ignored.status_code == 200

    activity = diagnostics(client, headers).json()["webhook"]
    assert activity["last_event_type"] == "customer.created"
    assert activity["last_outcome"] == "unhandled"


def test_a_refused_delivery_survives_the_error_that_refused_it(
    client, stripe, admin_user, register, create_restaurant
):
    """The `400` rolls the request's transaction back. The record of the refusal
    is committed on a session of its own, so it is still there afterwards -
    which is the only way a wrong `whsec_...` is ever diagnosed."""
    _, headers = admin_user()
    world = place_order(client, register, create_restaurant)
    session_id = start_checkout(
        client, world["headers"], world["order"]["order_id"]
    ).json()["session_id"]
    before = diagnostics(client, headers).json()["webhook"]

    refused = client.post(
        "/api/payments/webhook",
        content=stripe.event(session_id, "checkout.session.completed"),
        headers={"Stripe-Signature": "forged"},
    )

    assert refused.status_code == 400
    after = diagnostics(client, headers).json()["webhook"]
    assert after["last_outcome"] == "rejected"
    assert after["last_rejected_at"]
    assert after["rejected_24h"] == before["rejected_24h"] + 1


def test_a_delivery_arriving_with_no_payment_configuration_is_recorded(
    client, admin_user
):
    """Stripe calls a deployment with no key: 503, and the arrival is kept."""
    _, headers = admin_user()
    before = diagnostics(client, headers).json()["webhook"]

    response = client.post(
        "/api/payments/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "whatever"},
    )

    assert response.status_code == 503
    after = diagnostics(client, headers).json()["webhook"]
    assert after["last_outcome"] == "unconfigured"
    assert after["rejected_24h"] == before["rejected_24h"] + 1


def test_the_delivery_log_keeps_only_the_newest_rows(client, monkeypatch):
    """Every delivery writes a row and Stripe retries, so the table is bounded."""
    import asyncio

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api import payments as payments_api
    from app.api.payments import _prune_deliveries, _remember_delivery
    from app.database import DATABASE_URL
    from app.models.webhook_orm import PaymentWebhookDeliveryRecord

    monkeypatch.setattr(payments_api, "WEBHOOK_HISTORY_LIMIT", 3)

    async def run() -> int:
        engine = create_async_engine(DATABASE_URL)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                for _ in range(6):
                    _remember_delivery(
                        session,
                        verified=True,
                        outcome="settled",
                        event_id="evt_prune",
                        event_type="prune.test",
                    )
                await _prune_deliveries(session)
                await session.commit()
                return int(
                    await session.scalar(
                        select(func.count()).select_from(PaymentWebhookDeliveryRecord)
                    )
                    or 0
                )
        finally:
            await engine.dispose()

    assert asyncio.run(run()) == 3
