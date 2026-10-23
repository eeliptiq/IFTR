"""
Customer checkout: placing an order, reading it back, tipping, and reporting.

Until this slice existed nothing could create an order, so every screen in the
merged app - the kitchen queue, the driver's board, the customer's tracking page
- only ever had rows a script had written. These tests all start from the HTTP
endpoint a customer actually uses.

The pricing assertions are about what the *server* charges: the request carries
prices, and none of them are believed.
"""

import pytest

# The menu every test in this file checks out against. Sold-out and drink flags
# are the menu's, which is the point: the order inherits them.
MENU = [
    {"item_id": "item_pizza", "name": "Margherita", "price": 12.5, "is_available": True},
    {
        "item_id": "item_cola",
        "name": "Fountain Cola",
        "price": 3.0,
        "is_drink": True,
        "is_available": True,
    },
    {
        "item_id": "item_water",
        "name": "Bottled Water",
        "price": 2.0,
        "is_drink": True,
        "is_sealed": True,
        "is_available": True,
    },
    {"item_id": "item_tiramisu", "name": "Tiramisu", "price": 6.0, "is_available": False},
]

# The restaurant the create_restaurant fixture registers sits at 40.7 / -74.0.
DROP_2_KM_NORTH = (40.72, -74.0)


@pytest.fixture
def kitchen(client, register, create_restaurant):
    """A restaurant with a known menu: the restaurant, its owner, the menu."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner, name="Kebab Corner")
    saved = client.put(
        f"/api/restaurants/{restaurant['restaurant_id']}/menu",
        json=MENU,
        headers=owner,
    )
    assert saved.status_code == 200, saved.text
    return {"restaurant": restaurant, "headers": owner, "menu": saved.json()}


def place(client, headers, kitchen, items=None, **overrides):
    """Check out through the endpoint the checkout screen calls."""
    payload = {
        "restaurant_id": kitchen["restaurant"]["restaurant_id"],
        "items": items if items is not None else [{"item_id": "item_pizza", "quantity": 1}],
        "delivery_lat": DROP_2_KM_NORTH[0],
        "delivery_lng": DROP_2_KM_NORTH[1],
        "delivery_address": "9 Customer Rd",
        **overrides,
    }
    return client.post("/api/orders", json=payload, headers=headers)


def cook(client, owner_headers, order_id):
    """Walk an order to ready, the way the kitchen screen does."""
    for status in ("confirmed", "preparing", "ready"):
        moved = client.put(
            f"/api/orders/{order_id}/status?status={status}", headers=owner_headers
        )
        assert moved.status_code == 200, moved.text


def board_job(client, driver_headers, order_id):
    board = client.get("/api/drivers/available-orders", headers=driver_headers).json()
    return next(job for job in board if job["order_id"] == order_id)


# --------------------------------------------------------------------------
# Placing one
# --------------------------------------------------------------------------


def test_placing_an_order_requires_a_token(client, kitchen):
    assert place(client, None, kitchen).status_code == 401


def test_a_placed_order_lands_in_the_kitchen_queue(client, register, kitchen):
    """The queue the restaurant works is fed by checkout, not by a script."""
    customer, headers = register()
    created = place(client, headers, kitchen)

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "pending"
    assert body["customer_id"] == customer["user_id"]
    assert body["restaurant_name"] == "Kebab Corner"

    queue = client.get(
        f"/api/restaurants/{kitchen['restaurant']['restaurant_id']}/orders",
        headers=kitchen["headers"],
    ).json()
    assert body["order_id"] in {order["order_id"] for order in queue}


def test_an_unknown_restaurant_is_404(client, register):
    _, headers = register()
    response = client.post(
        "/api/orders",
        json={"restaurant_id": "rest_nope", "items": [{"item_id": "item_pizza"}]},
        headers=headers,
    )
    assert response.status_code == 404


def test_an_empty_cart_is_refused(client, register, kitchen):
    _, headers = register()
    assert place(client, headers, kitchen, items=[]).status_code == 422


# --------------------------------------------------------------------------
# What it costs
# --------------------------------------------------------------------------


def test_the_price_comes_from_the_menu_not_the_cart(client, register, kitchen):
    """A doctored request can change what is ordered, not what it costs."""
    _, headers = register()
    created = place(
        client,
        headers,
        kitchen,
        items=[{"item_id": "item_pizza", "quantity": 2, "price": 0.01}],
    )

    body = created.json()
    assert body["subtotal"] == 25.0
    assert body["items"][0]["base_price"] == 12.5
    # The tracking screen reads the same number under this name.
    assert body["items"][0]["price"] == 12.5


def test_the_delivery_fee_follows_the_speed_and_the_free_threshold(client, register, kitchen):
    """The fee the screen previews is the fee the server charges."""
    _, headers = register()

    standard = place(client, headers, kitchen).json()  # one 12.5 pizza
    assert standard["delivery_fee"] == 2.99
    assert standard["total_amount"] == pytest.approx(12.5 + 2.99, abs=0.001)

    priority = place(client, headers, kitchen, delivery_speed="priority").json()
    economy = place(client, headers, kitchen, delivery_speed="economy").json()
    assert priority["delivery_fee"] == pytest.approx(2.99 * 1.5, abs=0.02)
    assert economy["delivery_fee"] == pytest.approx(2.99 * 0.5, abs=0.02)

    # Over the threshold the courier's fee disappears.
    heavy = place(
        client, headers, kitchen, items=[{"item_id": "item_pizza", "quantity": 3}]
    ).json()
    assert heavy["subtotal"] == 37.5
    assert heavy["delivery_fee"] == 0.0


def test_the_tip_is_charged_once_and_shown_once(client, register, kitchen):
    _, headers = register()
    body = place(client, headers, kitchen, tip_amount=3).json()

    assert body["tip_amount"] == 3.0
    # Rounded to cents, so compared the way money is (12.5 + 2.99 + 3 is not
    # exactly 18.49 in binary floating point).
    assert body["total_amount"] == pytest.approx(12.5 + 2.99 + 3.0, abs=0.001)
    # What the courier is paid is the fee plus the tip.
    assert body["pay_amount"] == 5.99


def test_an_item_off_the_menu_is_refused(client, register, kitchen):
    """Priced from the request would mean priced from a stranger's number."""
    _, headers = register()
    response = place(client, headers, kitchen, items=[{"item_id": "item_ghost"}])

    assert response.status_code == 400
    assert "menu" in response.json()["detail"]


def test_an_item_the_kitchen_switched_off_is_refused(client, register, kitchen):
    _, headers = register()
    response = place(client, headers, kitchen, items=[{"item_id": "item_tiramisu"}])

    assert response.status_code == 409
    assert "no longer available" in response.json()["detail"]


def test_scheduling_is_refused_rather_than_ignored(client, register, kitchen):
    """Cooking a 7pm order now would tell the customer something untrue."""
    _, headers = register()
    response = place(client, headers, kitchen, scheduled_for="2026-12-24T19:00")

    assert response.status_code == 400
    assert "not supported" in response.json()["detail"]


# --------------------------------------------------------------------------
# The order the driver and the kitchen see
# --------------------------------------------------------------------------


def test_the_menu_marks_the_drinks_on_the_order(client, register, register_driver, kitchen):
    """
    The drink flags reach a real order here for the first time: checkout copies
    them from the menu, which is what the courier's cup-holder plan reads.
    """
    _, headers = register()
    created = place(
        client,
        headers,
        kitchen,
        items=[
            {"item_id": "item_pizza", "quantity": 1},
            {"item_id": "item_cola", "quantity": 2},
        ],
    ).json()

    assert created["has_drinks"] is True
    assert created["drink_count"] == 2
    assert created["unsealed_drink_count"] == 2

    cook(client, kitchen["headers"], created["order_id"])
    _, driver_headers, _ = register_driver(vehicle_type="bike")
    job = board_job(client, driver_headers, created["order_id"])

    assert job["requires_cup_holder"] is True
    assert job["restaurant_name"] == "Kebab Corner"
    assert job["distance_km"] == 2.2  # 0.02 degrees of latitude, rounded
    assert job["eta_minutes"] == 14  # 2.224 km at 14 km/h, plus the overhead


def test_sealed_drinks_ask_nothing_of_the_ride(client, register, register_driver, kitchen):
    _, headers = register()
    created = place(
        client, headers, kitchen, items=[{"item_id": "item_water", "quantity": 3}]
    ).json()
    cook(client, kitchen["headers"], created["order_id"])

    _, driver_headers, _ = register_driver(vehicle_type="bike")
    job = board_job(client, driver_headers, created["order_id"])

    assert job["drink_count"] == 3
    assert job["requires_cup_holder"] is False
    assert job["handling_notes"] == []


def test_the_checkout_choices_reach_the_driver(client, register, register_driver, kitchen):
    """What the customer picked at checkout is on the courier's card."""
    _, headers = register()
    created = place(
        client,
        headers,
        kitchen,
        delivery_instruction_type="leave_at_door",
        delivery_instructions="Flat 3, buzzer is broken",
        delivery_speed="priority",
    ).json()

    assert created["delivery_instruction_type"] == "leave_at_door"
    assert created["delivery_speed"] == "priority"

    cook(client, kitchen["headers"], created["order_id"])
    _, driver_headers, _ = register_driver()
    job = board_job(client, driver_headers, created["order_id"])

    assert job["delivery_instruction_type"] == "leave_at_door"
    assert job["delivery_speed"] == "priority"


def test_an_order_without_coordinates_is_still_offered(
    client, register, register_driver, kitchen
):
    _, headers = register()
    created = place(
        client, headers, kitchen, delivery_lat=None, delivery_lng=None
    ).json()
    cook(client, kitchen["headers"], created["order_id"])

    _, driver_headers, _ = register_driver()
    job = board_job(client, driver_headers, created["order_id"])

    assert job["distance_km"] is None
    assert job["eta_minutes"] is None


def test_the_order_carries_a_quote_for_the_customer(client, register, kitchen):
    """The tracking screen shows an ETA; it is the trip, quoted on a car."""
    _, headers = register()
    created = place(client, headers, kitchen).json()

    assert created["estimated_delivery_time"] == 10
    assert created["delivery_location"]["address"] == "9 Customer Rd"
    assert created["pickup_location"]["address"] == "1 Test St"


# --------------------------------------------------------------------------
# Reading them back
# --------------------------------------------------------------------------


def test_my_orders_are_mine_alone(client, register, kitchen):
    _, mine = register()
    _, theirs = register()

    place(client, mine, kitchen)
    place(client, theirs, kitchen, items=[{"item_id": "item_water"}])

    listed = client.get("/api/orders", headers=mine).json()
    assert len(listed) == 1
    assert listed[0]["items"][0]["item_id"] == "item_pizza"

    filtered = client.get("/api/orders?status=pending", headers=mine).json()
    assert len(filtered) == 1
    assert client.get("/api/orders?status=delivered", headers=mine).json() == []


def test_only_the_people_on_an_order_can_read_it(
    client, register, register_driver, kitchen
):
    _, customer = register()
    _, stranger = register()
    created = place(client, customer, kitchen).json()
    order_id = created["order_id"]

    assert client.get(f"/api/orders/{order_id}", headers=customer).status_code == 200
    # The kitchen making it, and only that kitchen.
    assert (
        client.get(f"/api/orders/{order_id}", headers=kitchen["headers"]).status_code
        == 200
    )
    assert client.get(f"/api/orders/{order_id}", headers=stranger).status_code == 403

    # The driver carrying it - and not before they take it.
    _, driver_headers, _ = register_driver()
    assert (
        client.get(f"/api/orders/{order_id}", headers=driver_headers).status_code == 403
    )
    cook(client, kitchen["headers"], order_id)
    assert client.post(
        f"/api/drivers/accept-order/{order_id}", headers=driver_headers
    ).status_code == 200
    assert (
        client.get(f"/api/orders/{order_id}", headers=driver_headers).status_code == 200
    )


def test_an_unknown_order_is_404(client, register):
    _, headers = register()
    assert client.get("/api/orders/order_nope", headers=headers).status_code == 404
    assert client.get("/api/orders", headers=headers).status_code == 200
    assert client.get("/api/orders").status_code == 401


# --------------------------------------------------------------------------
# Changing their mind, tipping, complaining
# --------------------------------------------------------------------------


def test_a_customer_may_cancel_while_the_kitchen_has_not_started(
    client, register, kitchen
):
    _, headers = register()

    fresh = place(client, headers, kitchen).json()
    cancelled = client.put(
        f"/api/orders/{fresh['order_id']}/status?status=cancelled", headers=headers
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    # Once food is being made the decision is the restaurant's, not theirs.
    cooking = place(client, headers, kitchen).json()
    client.put(
        f"/api/orders/{cooking['order_id']}/status?status=confirmed",
        headers=kitchen["headers"],
    )
    client.put(
        f"/api/orders/{cooking['order_id']}/status?status=preparing",
        headers=kitchen["headers"],
    )

    refused = client.put(
        f"/api/orders/{cooking['order_id']}/status?status=cancelled", headers=headers
    )
    assert refused.status_code == 409


def test_a_tip_only_goes_up_and_only_on_your_own_order(client, register, kitchen):
    _, headers = register()
    created = place(client, headers, kitchen, tip_amount=3).json()
    order_id = created["order_id"]

    added = client.post(
        f"/api/orders/{order_id}/add-tip", json={"amount": 2}, headers=headers
    )
    assert added.status_code == 200, added.text
    assert added.json()["additional_tip"] == 2.0
    assert added.json()["total_tip"] == 5.0

    after = client.get(f"/api/orders/{order_id}", headers=headers).json()
    assert after["tip_amount"] == 5.0
    assert after["total_amount"] == pytest.approx(12.5 + 2.99 + 5.0, abs=0.001)
    assert after["pay_amount"] == pytest.approx(2.99 + 5.0, abs=0.001)

    _, stranger = register()
    assert client.post(
        f"/api/orders/{order_id}/add-tip", json={"amount": 1}, headers=stranger
    ).status_code == 403
    assert client.post(
        f"/api/orders/{order_id}/add-tip", json={"amount": 0}, headers=headers
    ).status_code == 422

    client.put(
        f"/api/orders/{order_id}/status?status=cancelled", headers=headers
    )
    assert client.post(
        f"/api/orders/{order_id}/add-tip", json={"amount": 1}, headers=headers
    ).status_code == 409


def test_an_issue_is_written_down(client, register, kitchen):
    _, headers = register()
    order_id = place(client, headers, kitchen).json()["order_id"]

    reported = client.post(
        f"/api/orders/{order_id}/report-issue",
        json={"description": "The bag was missing the cola"},
        headers=headers,
    )
    assert reported.status_code == 201, reported.text
    assert reported.json()["issue_id"]

    _, stranger = register()
    assert client.post(
        f"/api/orders/{order_id}/report-issue",
        json={"description": "not mine"},
        headers=stranger,
    ).status_code == 403
    assert client.post(
        "/api/orders/order_nope/report-issue",
        json={"description": "nothing"},
        headers=headers,
    ).status_code == 404
