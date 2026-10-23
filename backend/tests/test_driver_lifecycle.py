"""
The driver's half of an order's life: signing up, the jobs on offer, claiming
one, and carrying it to the door.

The order lifecycle is split between two screens that call the *same* status
endpoint, so most of what matters here is who may take which step:

  * the restaurant may accept, cook and finish, and may not mark food delivered;
  * the driver may collect, travel and deliver, and may not move an order that
    is not theirs;
  * an unclaimed job on the board tells a driver what the work is, not who the
    customer is or where they live.

The refusals are the point. A refusal that returns the wrong code, or that lets
the wrong person through, is the failure this suite exists to catch.
"""

import datetime

UTC = datetime.timezone.utc

PENDING = "pending"
CONFIRMED = "confirmed"
PREPARING = "preparing"
READY = "ready"
ASSIGNED = "assigned"
PICKED_UP = "picked_up"
IN_TRANSIT = "in_transit"
DELIVERED = "delivered"
CANCELLED = "cancelled"

DRIVER_NOT_FOUND = "Driver not found"


def status_url(order_id: str, status: str) -> str:
    return f"/api/orders/{order_id}/status?status={status}"


def stored(scalar, column: str, order_id: str):
    return scalar(f"select {column} from orders where order_id = ?", (order_id,))


def available_ids(client, headers) -> list:
    response = client.get("/api/drivers/available-orders", headers=headers)
    assert response.status_code == 200, response.text
    return [order["order_id"] for order in response.json()]


# --------------------------------------------------------------------------
# Signing up
# --------------------------------------------------------------------------


def test_registering_as_a_driver_requires_a_token(client):
    response = client.post(
        "/api/drivers/register", json={"vehicle_type": "car", "license_number": "DL-1"}
    )
    assert response.status_code == 401


def test_an_unregistered_user_is_told_the_driver_is_missing(client, register):
    """
    The screen decides to offer registration from this exact 404 and detail
    string, so both are part of the interface.
    """
    _, headers = register()

    response = client.get("/api/drivers/profile", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == DRIVER_NOT_FOUND


def test_registering_makes_a_driver_with_a_profile(client, register):
    _, headers = register()
    created = client.post(
        "/api/drivers/register",
        json={"vehicle_type": "bike", "license_number": "DL-999"},
        headers=headers,
    )
    assert created.status_code == 201, created.text

    body = created.json()
    assert body["driver_id"].startswith("driver")
    assert body["vehicle_type"] == "bike"
    assert body["is_available"] is True

    profile = client.get("/api/drivers/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["driver_id"] == body["driver_id"]
    assert profile.json()["has_license"] is True


def test_registering_promotes_the_account(client, register, register_driver):
    _, headers = register()
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "customer"

    client.post(
        "/api/drivers/register",
        json={"vehicle_type": "car", "license_number": "DL-1"},
        headers=headers,
    )
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "driver"


def test_a_driver_cannot_register_twice(client, register_driver):
    _, headers, _ = register_driver()

    again = client.post(
        "/api/drivers/register",
        json={"vehicle_type": "car", "license_number": "DL-2"},
        headers=headers,
    )
    assert again.status_code == 400
    assert "already" in again.json()["detail"].lower()


def test_the_licence_number_never_comes_back(client, register_driver, scalar):
    """A licence identifies a person: it is stored encrypted and never returned."""
    _, headers, _ = register_driver(license_number="SECRET-LICENCE-42")

    for response in (
        client.get("/api/drivers/profile", headers=headers),
        client.put("/api/drivers/vehicle", json={"vehicle_type": "car"}, headers=headers),
    ):
        assert response.status_code == 200
        assert "SECRET-LICENCE-42" not in response.text
        assert "license_number" not in response.text

    # ...and is not sitting in the database in the clear either.
    user_id = client.get("/api/auth/me", headers=headers).json()["user_id"]
    encrypted = scalar(
        "select license_number_encrypted from drivers where user_id = ?", (user_id,)
    )
    assert encrypted and "SECRET-LICENCE-42" not in encrypted


def test_the_vehicle_can_be_changed(client, register_driver):
    _, headers, _ = register_driver(vehicle_type="car")

    response = client.put(
        "/api/drivers/vehicle", json={"vehicle_type": "motorcycle"}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["vehicle_type"] == "motorcycle"

    assert client.get("/api/drivers/profile", headers=headers).json()["vehicle_type"] == (
        "motorcycle"
    )


def test_the_walk_vehicle_the_screen_offers_is_accepted(client, register_driver):
    """The driver form offers 'walk', so VehicleType defines it."""
    _, headers, _ = register_driver(vehicle_type="walk")

    response = client.put(
        "/api/drivers/vehicle", json={"vehicle_type": "walk"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["vehicle_type"] == "walk"


def test_the_vehicles_the_screen_offers_are_all_in_the_model():
    """The form may offer a subset of VehicleType, never a value outside it."""
    from app.models.general import VehicleType

    offered = {"car", "bike", "motorcycle", "walk"}  # DriverDeliveries.js
    assert offered <= {vehicle.value for vehicle in VehicleType}


def test_an_unknown_vehicle_is_refused(client, register):
    """Validation is real now, so a typo cannot be stored as a driver's vehicle."""
    _, headers = register()

    response = client.post(
        "/api/drivers/register",
        json={"vehicle_type": "spaceship", "license_number": "DL-1"},
        headers=headers,
    )
    assert response.status_code == 422


def test_the_board_flags_a_drink(client, register, register_driver, create_restaurant, seed_order):
    """A drink travels differently, so the courier is told before taking the job."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    dry = seed_order(restaurant["restaurant_id"], status=READY)
    wet = seed_order(
        restaurant["restaurant_id"],
        status=READY,
        items=[
            {"item_id": "i1", "name": "Margherita", "quantity": 1, "base_price": 12.5},
            {"item_id": "i2", "name": "Cola", "quantity": 2, "base_price": 3.0, "is_drink": True},
        ],
    )

    _, driver_headers, _ = register_driver()
    board = {
        order["order_id"]: order
        for order in client.get("/api/drivers/available-orders", headers=driver_headers).json()
    }

    assert board[wet["order_id"]]["has_drinks"] is True
    assert board[dry["order_id"]]["has_drinks"] is False
    assert board[wet["order_id"]]["item_count"] == 3


# --------------------------------------------------------------------------
# Handling plan: what the order asks of the ride
# --------------------------------------------------------------------------


DRINK_ITEMS = [
    {"item_id": "i1", "name": "Margherita", "quantity": 1, "base_price": 12.5},
    {
        "item_id": "i2",
        "name": "Cola",
        "quantity": 2,
        "base_price": 3.0,
        "is_drink": True,
    },
]

PLAIN_ITEM = {"item_id": "i1", "name": "Margherita", "quantity": 1}


def board_job(client, headers, order_id: str) -> dict:
    """The offer for one order, as this driver's vehicle sees it."""
    board = {
        order["order_id"]: order
        for order in client.get("/api/drivers/available-orders", headers=headers).json()
    }
    return board[order_id]


def test_a_bike_driver_is_told_to_bring_a_cup_holder(
    client, register, register_driver, create_restaurant, seed_order
):
    """A bicycle has nowhere to stand a cup, so the work needs a cup holder."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    wet = seed_order(restaurant["restaurant_id"], status=READY, items=DRINK_ITEMS)

    _, driver_headers, _ = register_driver(vehicle_type="bike")
    job = board_job(client, driver_headers, wet["order_id"])

    assert job["drink_count"] == 2
    assert job["requires_cup_holder"] is True
    assert len(job["handling_notes"]) == 2
    assert any("keep them upright" in note for note in job["handling_notes"])
    assert any("cup holder" in note for note in job["handling_notes"])


def test_a_walker_is_told_to_bring_a_cup_holder(
    client, register, register_driver, create_restaurant, seed_order
):
    """On foot is the other end of the same problem: two free hands, two drinks."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    wet = seed_order(restaurant["restaurant_id"], status=READY, items=DRINK_ITEMS)

    _, driver_headers, _ = register_driver(vehicle_type="walk")
    job = board_job(client, driver_headers, wet["order_id"])

    assert job["requires_cup_holder"] is True


def test_a_car_driver_needs_no_cup_holder_but_still_sees_the_unsealed_count(
    client, register, register_driver, create_restaurant, seed_order
):
    """A car has cup holders, so the flag is off - but the drinks are still flagged."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    wet = seed_order(restaurant["restaurant_id"], status=READY, items=DRINK_ITEMS)

    _, driver_headers, _ = register_driver(vehicle_type="car")
    job = board_job(client, driver_headers, wet["order_id"])

    assert job["unsealed_drink_count"] == 2
    assert job["requires_cup_holder"] is False
    assert job["handling_notes"] == ["Carry 2 unsealed drinks and keep them upright."]


SEALED_ITEMS = [
    {"item_id": "i1", "name": "Margherita", "quantity": 1, "base_price": 12.5},
    {
        "item_id": "i2",
        "name": "Bottled Water",
        "quantity": 3,
        "base_price": 2.0,
        "is_drink": True,
        "is_sealed": True,
    },
]


def test_sealed_drinks_ask_nothing_of_the_ride(
    client, register, register_driver, create_restaurant, seed_order
):
    """A bottle is cargo: a cyclist carrying water needs no cup holder for it."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    sealed = seed_order(restaurant["restaurant_id"], status=READY, items=SEALED_ITEMS)

    _, driver_headers, _ = register_driver(vehicle_type="bike")
    job = board_job(client, driver_headers, sealed["order_id"])

    assert job["has_drinks"] is True
    assert job["drink_count"] == 3
    assert job["unsealed_drink_count"] == 0
    assert job["requires_cup_holder"] is False
    assert job["handling_notes"] == []


def test_a_dry_order_carries_no_handling_plan(
    client, register, register_driver, create_restaurant, seed_order
):
    """Most orders ask nothing special, and the screen should say nothing."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    dry = seed_order(restaurant["restaurant_id"], status=READY, items=[PLAIN_ITEM])

    _, driver_headers, _ = register_driver(vehicle_type="bike")
    job = board_job(client, driver_headers, dry["order_id"])

    assert job["drink_count"] == 0
    assert job["requires_cup_holder"] is False
    assert job["handling_notes"] == []


def test_the_job_in_hand_is_planned_against_the_current_vehicle(
    client, register, register_driver, create_restaurant, seed_order
):
    """Switching vehicles re-plans the job already in hand, at both ends.

    A driver who claimed a drink order in a car and then swapped to a bicycle
    must be told about the cup holder when they reload their delivery, not only
    at the moment they accepted it.
    """
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    wet = seed_order(restaurant["restaurant_id"], status=READY, items=DRINK_ITEMS)

    _, driver_headers, _ = register_driver(vehicle_type="car")
    accepted = client.post(
        f"/api/drivers/accept-order/{wet['order_id']}", headers=driver_headers
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["requires_cup_holder"] is False
    assert accepted.json()["drink_count"] == 2

    assert client.put(
        "/api/drivers/vehicle", json={"vehicle_type": "bike"}, headers=driver_headers
    ).status_code == 200

    active = client.get("/api/drivers/active-delivery", headers=driver_headers).json()
    assert active["order_id"] == wet["order_id"]
    assert active["requires_cup_holder"] is True
    assert any("cup holder" in note for note in active["handling_notes"])

    # And the re-plan does not accumulate: back on four wheels, the note is gone.
    client.put(
        "/api/drivers/vehicle", json={"vehicle_type": "car"}, headers=driver_headers
    )
    again = client.get("/api/drivers/active-delivery", headers=driver_headers).json()
    assert again["requires_cup_holder"] is False
    assert again["handling_notes"] == ["Carry 2 unsealed drinks and keep them upright."]


# --------------------------------------------------------------------------
# The trip: how far, which way, and how long
# --------------------------------------------------------------------------

# The restaurant the create_restaurant fixture registers sits at 40.7 / -74.0
# (see conftest), so these dropoffs are deltas from a known point:
DUE_EAST = (40.7, -73.98)  # ~1.7 km, bearing east
NORTH = (40.72, -74.0)  # ~2.2 km, bearing north
FAR_NORTH = (40.772, -74.0)  # ~8 km: a drive, or two hours on foot


def test_the_offer_quotes_distance_direction_pay_and_the_kitchen(
    client, register, register_driver, create_restaurant, seed_order
):
    """What a driver decides on: far, which way, what for, and from where."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner, name="Kebab Corner")
    order = seed_order(restaurant["restaurant_id"], status=READY, dropoff=DUE_EAST)

    _, driver_headers, _ = register_driver(vehicle_type="car")
    job = board_job(client, driver_headers, order["order_id"])

    assert job["restaurant_name"] == "Kebab Corner"
    assert job["distance_km"] == 1.7
    assert job["dropoff_direction"] == "E"
    assert round(job["dropoff_bearing"]) == 90
    assert job["eta_minutes"] == 8  # 1.7 km at 24 km/h plus the overhead
    # Fee plus tip is what the courier is paid, so the screen never adds it up.
    assert job["pay_amount"] == 5.99
    assert job["item_count"] == 2


def test_an_order_too_far_for_the_vehicle_is_not_offered(
    client, register, register_driver, create_restaurant, seed_order
):
    """The same eight kilometres is work in a car and not on foot."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY, dropoff=FAR_NORTH)

    _, walker, _ = register_driver(vehicle_type="walk")
    _, driver, _ = register_driver(vehicle_type="car")

    assert order["order_id"] not in available_ids(client, walker)

    job = board_job(client, driver, order["order_id"])
    assert job["distance_km"] == 8.0
    assert job["eta_minutes"] == 24


def test_an_order_nobody_has_located_is_still_offered(
    client, register, register_driver, create_restaurant, seed_order
):
    """Missing data is not the same as an unrealistic trip."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    job = board_job(client, driver_headers, order["order_id"])

    assert job["distance_km"] is None
    assert job["eta_minutes"] is None
    assert job["dropoff_direction"] is None


def test_the_board_is_ranked_by_how_quick_the_trip_is(
    client, register, register_driver, create_restaurant, seed_order
):
    """A driver reads the board top-down, so the quickest work is on top."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    far = seed_order(restaurant["restaurant_id"], status=READY, dropoff=FAR_NORTH)
    near = seed_order(restaurant["restaurant_id"], status=READY, dropoff=DUE_EAST)

    _, driver_headers, _ = register_driver(vehicle_type="car")
    board = available_ids(client, driver_headers)

    assert board.index(near["order_id"]) < board.index(far["order_id"])


def test_the_dropoff_is_encrypted_at_rest(
    client, register, register_driver, create_restaurant, seed_order, scalar
):
    """The distance and the arrow are offered; the address behind them is not."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY, dropoff=DUE_EAST)

    lat = scalar(
        "select lat_encrypted from order_locations where order_id = ?",
        (order["order_id"],),
    )

    assert lat and "40.7" not in lat

    from app.core.encryption import decrypt_data

    assert decrypt_data(lat) == "40.7"


# --------------------------------------------------------------------------
# Rejecting a job
# --------------------------------------------------------------------------


def test_a_rejected_job_leaves_only_that_drivers_board(
    client, register, register_driver, create_restaurant, seed_order
):
    """A decline is personal: the work stays available to every other driver."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    wet = seed_order(restaurant["restaurant_id"], status=READY, items=DRINK_ITEMS)

    _, choosy, _ = register_driver(vehicle_type="walk")
    _, willing, _ = register_driver(vehicle_type="car")

    for _ in range(2):  # a double-tap is one fact, not an error
        declined = client.post(
            f"/api/drivers/decline-order/{wet['order_id']}", headers=choosy
        )
        assert declined.status_code == 204, declined.text

    assert wet["order_id"] not in available_ids(client, choosy)
    assert wet["order_id"] in available_ids(client, willing)


def test_a_rejected_job_can_be_asked_for_again_and_taken(
    client, register, register_driver, create_restaurant, seed_order
):
    """The screen's "show rejected orders" button, end to end.

    Asking for the job back is not the same as having it: the flag says which
    cards the driver already turned down, and accepting one still goes through
    the same claim as any other, which is what keeps a revived offer honest if
    somebody else took it in the meantime.
    """
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY, dropoff=DUE_EAST)

    _, driver_headers, _ = register_driver()
    assert client.post(
        f"/api/drivers/decline-order/{order['order_id']}", headers=driver_headers
    ).status_code == 204
    assert order["order_id"] not in available_ids(client, driver_headers)

    revived = client.get(
        "/api/drivers/available-orders?include_rejected=true", headers=driver_headers
    ).json()
    revived = {job["order_id"]: job for job in revived}

    assert revived[order["order_id"]]["was_rejected"] is True

    accepted = client.post(
        f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["pay_amount"] == 5.99
    assert accepted.json()["distance_km"] == 1.7


def flags_for(board: list, order_id: str) -> bool:
    """The rejection flag the board carries for one order."""
    return next(job["was_rejected"] for job in board if job["order_id"] == order_id)


def test_a_revived_job_is_only_flagged_for_the_driver_who_passed_on_it(
    client, register, register_driver, create_restaurant, seed_order
):
    """A decline is personal, so the flag has to be too."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, choosy, _ = register_driver()
    _, other, _ = register_driver()
    client.post(f"/api/drivers/decline-order/{order['order_id']}", headers=choosy)

    flagged = client.get(
        "/api/drivers/available-orders?include_rejected=true", headers=choosy
    ).json()
    untouched = client.get(
        "/api/drivers/available-orders?include_rejected=true", headers=other
    ).json()

    assert flags_for(flagged, order["order_id"]) is True
    assert flags_for(untouched, order["order_id"]) is False


def test_an_order_someone_is_carrying_cannot_be_rejected(
    client, register, register_driver, create_restaurant, seed_order
):
    """By the time another driver taps reject, the work is no longer on offer."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, carrier, _ = register_driver()
    _, other, _ = register_driver()

    assert client.post(
        f"/api/drivers/accept-order/{order['order_id']}", headers=carrier
    ).status_code == 200

    rejected = client.post(
        f"/api/drivers/decline-order/{order['order_id']}", headers=other
    )
    assert rejected.status_code == 409


def test_rejecting_an_unknown_order_is_404(client, register_driver):
    _, headers, _ = register_driver()
    response = client.post("/api/drivers/decline-order/order_nope", headers=headers)
    assert response.status_code == 404


def test_rejecting_needs_a_token_and_a_driver_record(client, register):
    assert client.post("/api/drivers/decline-order/order_x").status_code == 401

    _, headers = register()  # a real account, just not a driver
    response = client.post("/api/drivers/decline-order/order_x", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == DRIVER_NOT_FOUND


def test_vehicle_and_availability_need_a_driver_record(client, register, create_restaurant):
    _, headers = register(role="restaurant_admin")
    create_restaurant(headers)  # a real account, just not a driver

    assert client.put(
        "/api/drivers/vehicle", json={"vehicle_type": "car"}, headers=headers
    ).status_code == 404
    assert client.put(
        "/api/drivers/availability?is_available=false", headers=headers
    ).status_code == 404


def test_going_offline_empties_the_board(client, register_driver, register, create_restaurant, seed_order):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    assert available_ids(client, driver_headers) != []

    offline = client.put(
        "/api/drivers/availability?is_available=false", headers=driver_headers
    )
    assert offline.status_code == 200
    assert offline.json()["is_available"] is False

    assert available_ids(client, driver_headers) == []


# --------------------------------------------------------------------------
# The board
# --------------------------------------------------------------------------


def test_the_board_requires_a_token(client):
    assert client.get("/api/drivers/available-orders").status_code == 401


def test_the_board_needs_a_driver_record(client, register):
    _, headers = register()
    response = client.get("/api/drivers/available-orders", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == DRIVER_NOT_FOUND


def test_only_ready_orders_are_on_the_board(
    client, register, register_driver, create_restaurant, seed_order
):
    """Food that is not cooked yet is not a job anyone can take.

    The board is every restaurant's, not one kitchen's, so the assertions are
    about the orders this test created rather than about the whole list.
    """
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    not_ready = {
        seed_order(restaurant["restaurant_id"], status=status)["order_id"]
        for status in (PENDING, CONFIRMED, PREPARING)
    }
    ready = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    board = set(available_ids(client, driver_headers))

    assert ready["order_id"] in board
    assert not (not_ready & board)


def test_a_claimed_order_leaves_the_board(
    client, register, register_driver, create_restaurant, seed_order
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    assert order["order_id"] in available_ids(client, driver_headers)

    client.post(f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers)

    assert order["order_id"] not in available_ids(client, driver_headers)


def test_the_board_is_oldest_first(
    client, register, register_driver, create_restaurant, seed_order
):
    """The order that has been waiting longest is offered first."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    older = seed_order(
        restaurant["restaurant_id"],
        status=READY,
        created_at=datetime.datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    )
    newer = seed_order(
        restaurant["restaurant_id"],
        status=READY,
        created_at=datetime.datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
    )

    _, driver_headers, _ = register_driver()
    board = available_ids(client, driver_headers)

    assert board.index(older["order_id"]) < board.index(newer["order_id"])


def test_a_job_offer_does_not_give_away_the_customer(
    client, register, register_driver, create_restaurant, seed_order
):
    """
    A driver still choosing whether to take the work has no business knowing
    where the customer lives or how to get in.
    """
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    response = client.get("/api/drivers/available-orders", headers=driver_headers)
    assert response.status_code == 200

    offered = next(
        entry for entry in response.json() if entry["order_id"] == order["order_id"]
    )
    # The whole board, not just this order: no offer ever carries the customer.
    assert "9 Customer Rd" not in response.text
    assert "Leave at door" not in response.text
    assert offered["delivery_address"] == ""
    assert offered["delivery_instructions"] == ""
    assert offered["customer_name"] == ""
    assert offered["customer_id"] == ""

    # What a driver does need to choose: the size of the job and what it pays.
    assert offered["item_count"] == 2
    assert offered["delivery_fee"] == 2.99
    assert offered["tip_amount"] == 3.0
    assert offered["items"][0]["name"] == "Margherita"


# --------------------------------------------------------------------------
# Claiming
# --------------------------------------------------------------------------


def test_a_driver_claims_a_ready_order(
    client, register, register_driver, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, driver = register_driver()
    response = client.post(
        f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == ASSIGNED

    assert stored(scalar, "status", order["order_id"]) == ASSIGNED
    assert stored(scalar, "driver_id", order["order_id"]) == driver["driver_id"]
    assert stored(scalar, "assigned_at", order["order_id"])


def test_claiming_a_job_tells_the_driver_where_to_collect_it(
    client, register, register_driver, create_restaurant, seed_order
):
    """The next thing the driver does is drive to the restaurant."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    claimed = client.post(
        f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers
    ).json()

    assert claimed["pickup_location"]["address"] == "1 Test St"
    assert claimed["pickup_location"]["city"] == "NYC"
    assert claimed["delivery_location"]["address"] == "9 Customer Rd"


def test_claiming_requires_a_driver_record(
    client, register, register_driver, create_restaurant, seed_order
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, bystander = register()
    response = client.post(
        f"/api/drivers/accept-order/{order['order_id']}", headers=bystander
    )
    assert response.status_code == 404
    assert response.json()["detail"] == DRIVER_NOT_FOUND


def test_an_order_that_is_not_ready_cannot_be_claimed(
    client, register, register_driver, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=PREPARING)

    _, driver_headers, _ = register_driver()
    response = client.post(
        f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers
    )
    assert response.status_code == 409
    assert PREPARING in response.json()["detail"]

    assert stored(scalar, "status", order["order_id"]) == PREPARING
    assert stored(scalar, "driver_id", order["order_id"]) is None


def test_two_drivers_cannot_claim_the_same_job(
    client, register, register_driver, create_restaurant, seed_order, scalar
):
    """The claim is one conditional write, so the loser is told, not overwritten."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, first_headers, first = register_driver()
    _, second_headers, second = register_driver()

    assert client.post(
        f"/api/drivers/accept-order/{order['order_id']}", headers=first_headers
    ).status_code == 200

    stolen = client.post(
        f"/api/drivers/accept-order/{order['order_id']}", headers=second_headers
    )
    assert stolen.status_code == 409
    assert "taken" in stolen.json()["detail"].lower()

    # and the job still belongs to whoever got there first
    assert stored(scalar, "driver_id", order["order_id"]) == first["driver_id"]
    assert second["driver_id"] != first["driver_id"]


def test_claiming_an_unknown_order_is_404(client, register_driver):
    _, driver_headers, _ = register_driver()
    response = client.post(
        "/api/drivers/accept-order/order_does_not_exist", headers=driver_headers
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Carrying it
# --------------------------------------------------------------------------


def test_the_whole_handover(client, register, register_driver, create_restaurant, seed_order, scalar):
    """
    The point of the slice: one order, cooked by the kitchen and carried by a
    driver, all the way to the door.
    """
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"])
    order_id = order["order_id"]

    # The kitchen works its side.
    for step in (CONFIRMED, PREPARING, READY):
        response = client.put(status_url(order_id, step), headers=owner)
        assert response.status_code == 200, f"kitchen {step}: {response.text}"

    # A driver picks it up.
    _, driver_headers, driver = register_driver()
    assert order_id in available_ids(client, driver_headers)
    assert client.post(
        f"/api/drivers/accept-order/{order_id}", headers=driver_headers
    ).status_code == 200

    # ...and carries it.
    for step in (PICKED_UP, IN_TRANSIT, DELIVERED):
        response = client.put(status_url(order_id, step), headers=driver_headers)
        assert response.status_code == 200, f"driver {step}: {response.text}"
        assert response.json()["status"] == step

    assert stored(scalar, "status", order_id) == DELIVERED
    assert stored(scalar, "delivered_at", order_id)

    # The customer-facing end state: off the board and off the driver's plate.
    assert order_id not in available_ids(client, driver_headers)
    assert client.get("/api/drivers/active-delivery", headers=driver_headers).json() is None


def test_each_driver_step_is_stamped(
    client, register, register_driver, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    client.post(f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers)

    for step, column in (
        (PICKED_UP, "picked_up_at"),
        (IN_TRANSIT, None),  # no column of its own; the status carries it
        (DELIVERED, "delivered_at"),
    ):
        assert client.put(status_url(order["order_id"], step), headers=driver_headers).status_code == 200
        if column:
            assert stored(scalar, column, order["order_id"]), column

    assert stored(scalar, "status", order["order_id"]) == DELIVERED


def test_the_driver_cannot_skip_a_step(
    client, register, register_driver, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    client.post(f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers)

    for shortcut in (IN_TRANSIT, DELIVERED):
        response = client.put(status_url(order["order_id"], shortcut), headers=driver_headers)
        assert response.status_code == 409, shortcut

    assert stored(scalar, "status", order["order_id"]) == ASSIGNED


def test_the_driver_cannot_walk_an_order_back(
    client, register, register_driver, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    client.post(f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers)

    response = client.put(status_url(order["order_id"], READY), headers=driver_headers)
    assert response.status_code == 409
    assert stored(scalar, "status", order["order_id"]) == ASSIGNED


def test_another_driver_cannot_carry_someone_elses_job(
    client, register, register_driver, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, mine, _ = register_driver()
    _, theirs, _ = register_driver()
    client.post(f"/api/drivers/accept-order/{order['order_id']}", headers=mine)

    response = client.put(status_url(order["order_id"], PICKED_UP), headers=theirs)
    assert response.status_code == 403

    assert stored(scalar, "status", order["order_id"]) == ASSIGNED


def test_a_customer_cannot_advance_an_order(
    client, register, register_driver, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    client.post(f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers)

    _, bystander = register()  # neither the restaurant nor the driver
    response = client.put(status_url(order["order_id"], PICKED_UP), headers=bystander)
    assert response.status_code == 403

    assert stored(scalar, "status", order["order_id"]) == ASSIGNED


def test_the_kitchen_still_cannot_mark_food_delivered(
    client, register, register_driver, create_restaurant, seed_order, scalar
):
    """Two kinds of refusal, by design: an edge nobody has, and one that is not yours."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    # ready -> delivered is not an edge at all.
    not_an_edge = client.put(status_url(order["order_id"], DELIVERED), headers=owner)
    assert not_an_edge.status_code == 409

    _, driver_headers, _ = register_driver()
    client.post(f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers)

    # assigned -> picked_up exists, but it belongs to the driver.
    not_theirs = client.put(status_url(order["order_id"], PICKED_UP), headers=owner)
    assert not_theirs.status_code == 403
    assert "restaurant" in not_theirs.json()["detail"]

    assert stored(scalar, "status", order["order_id"]) == ASSIGNED


def test_the_kitchen_cannot_cancel_once_a_driver_is_coming(
    client, register, register_driver, create_restaurant, seed_order, scalar
):
    """A driver on the road is not something a kitchen can undo."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    client.post(f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers)

    response = client.put(status_url(order["order_id"], CANCELLED), headers=owner)
    assert response.status_code == 409
    assert stored(scalar, "status", order["order_id"]) == ASSIGNED


# --------------------------------------------------------------------------
# The active job
# --------------------------------------------------------------------------


def test_the_active_job_is_null_when_there_is_none(client, register_driver):
    """
    Null, not 404: the screen asks on every poll and reads the answer as "what
    am I carrying", so a 404 would break the page load.
    """
    _, driver_headers, _ = register_driver()

    response = client.get("/api/drivers/active-delivery", headers=driver_headers)
    assert response.status_code == 200
    assert response.json() is None


def test_the_active_job_has_both_ends_of_the_trip(
    client, register, register_driver, create_restaurant, seed_order
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    client.post(f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers)

    active = client.get("/api/drivers/active-delivery", headers=driver_headers).json()
    assert active["order_id"] == order["order_id"]
    assert active["status"] == ASSIGNED
    assert active["pickup_location"]["address"] == "1 Test St"
    assert active["delivery_location"]["address"] == "9 Customer Rd"
    assert active["delivery_location"]["zip_code"] == "10002"
    assert active["delivery_instructions"] == "Leave at door"
    # still not the customer's identity
    assert active["customer_name"] == ""


def test_the_active_job_tracks_the_driver_through_the_steps(
    client, register, register_driver, create_restaurant, seed_order
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    client.post(f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers)

    for step in (PICKED_UP, IN_TRANSIT):
        client.put(status_url(order["order_id"], step), headers=driver_headers)
        active = client.get("/api/drivers/active-delivery", headers=driver_headers).json()
        assert active["status"] == step


def test_the_active_job_needs_a_driver_record(client, register):
    _, headers = register()
    response = client.get("/api/drivers/active-delivery", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == DRIVER_NOT_FOUND


def test_a_drivers_finished_job_is_not_their_active_job(
    client, register, register_driver, create_restaurant, seed_order
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    order = seed_order(restaurant["restaurant_id"], status=READY)

    _, driver_headers, _ = register_driver()
    client.post(f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers)
    for step in (PICKED_UP, IN_TRANSIT, DELIVERED):
        client.put(status_url(order["order_id"], step), headers=driver_headers)

    assert client.get("/api/drivers/active-delivery", headers=driver_headers).json() is None


# --------------------------------------------------------------------------
# The shape of the rules
# --------------------------------------------------------------------------


def test_every_role_edge_is_a_reachable_edge():
    """A role may never be allowed to take an edge the graph does not have."""
    from app.order_flow import OrderFlowManager

    for actor, edges in OrderFlowManager.ROLE_TRANSITIONS.items():
        for current, allowed in edges.items():
            reachable = set(OrderFlowManager.TRANSITION_RULES.get(current, []))
            assert allowed <= reachable, f"{actor}: {current} -> {allowed - reachable}"


def test_claiming_is_the_only_way_to_reach_assigned():
    """
    ready -> assigned is in the graph but in no role's set: claiming has to stamp
    the driver onto the order, so it is not a bare status change.
    """
    from app.models.general import OrderStatus
    from app.order_flow import OrderFlowManager

    assert OrderStatus.ASSIGNED in OrderFlowManager.TRANSITION_RULES[OrderStatus.READY]

    for actor, edges in OrderFlowManager.ROLE_TRANSITIONS.items():
        for current, allowed in edges.items():
            assert OrderStatus.ASSIGNED not in allowed, actor


def test_the_restaurant_and_driver_halves_do_not_overlap():
    """One actor per edge, so no step can be taken by both."""
    from app.order_flow import DRIVER, RESTAURANT
    from app.order_flow import OrderFlowManager

    restaurant_edges = {
        (current, nxt)
        for current, allowed in OrderFlowManager.ROLE_TRANSITIONS[RESTAURANT].items()
        for nxt in allowed
    }
    driver_edges = {
        (current, nxt)
        for current, allowed in OrderFlowManager.ROLE_TRANSITIONS[DRIVER].items()
        for nxt in allowed
    }

    assert not (restaurant_edges & driver_edges)
