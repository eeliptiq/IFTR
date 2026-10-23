"""Surplus food: listing it, reserving it, and carrying it.

The suite shares one database, so assertions are made against the rows a test
created (by id) rather than against "the list is empty" - another test's
volunteer run is allowed to be sitting on the board.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.encryption import decrypt_data


@pytest.fixture
def listing(client, register, create_restaurant):
    """A restaurant owner and one live listing of that restaurant's food."""

    def _create(**overrides):
        owner, headers = register()
        restaurant = create_restaurant(
            headers,
            name="Surplus Kitchen",
            address="1 Test St",
            city="NYC",
            zip_code="10001",
        )
        payload = {
            "description": "10 portions of pasta",
            "quantity": 5,
            "original_price": 50.0,
            "discounted_price": 0.0,
            "expiry_hours": 4,
            **overrides,
        }
        response = client.post("/api/surplus", json=payload, headers=headers)
        assert response.status_code == 201, response.text
        return headers, restaurant, response.json()

    return _create


@pytest.fixture
def organization(client, register, create_organization, verify_organization):
    """A registered organization, verified unless told otherwise."""

    def _create(verified: bool = True, **overrides):
        user, headers = register()
        record = create_organization(headers, **overrides)
        if verified:
            verify_organization(record["org_id"])
        return user, headers, record

    return _create


def reserve(client, headers, surplus_id, quantity=None):
    body = {} if quantity is None else {"quantity": quantity}
    return client.post(
        f"/api/surplus/{surplus_id}/reserve", json=body, headers=headers
    )


# --------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------


def test_listing_requires_a_restaurant(client, register):
    _, headers = register()

    response = client.post(
        "/api/surplus",
        json={"description": "Leftovers", "quantity": 2, "original_price": 10},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Must be a restaurant owner"


def test_listing_takes_its_pickup_point_from_the_restaurant(
    client, listing, scalar
):
    _, restaurant, surplus = listing()

    assert surplus["restaurant_id"] == restaurant["restaurant_id"]
    assert surplus["restaurant_name"] == "Surplus Kitchen"
    assert surplus["quantity"] == 5
    assert surplus["is_available"] is True
    assert surplus["pickup_city"] == "NYC"
    # SQLite hands back naive datetimes; the wire format has to carry UTC or the
    # browser counts the expiry down from the wrong moment.
    assert surplus["expiry_time"].endswith(("+00:00", "Z"))

    # The browsing page has no business with the kitchen's exact door; the
    # volunteer gets it when they take the run.
    assert "address" not in surplus
    assert "1 Test St" not in str(surplus)

    stored = scalar(
        "SELECT pickup_lat_encrypted FROM surplus_food WHERE surplus_id = ?",
        (surplus["surplus_id"],),
    )
    assert stored and stored != "40.7"
    assert float(decrypt_data(stored)) == pytest.approx(40.7)


def test_asking_price_above_the_value_is_refused(client, register, create_restaurant):
    _, headers = register()
    create_restaurant(headers)

    response = client.post(
        "/api/surplus",
        json={
            "description": "Mystery box",
            "quantity": 3,
            "original_price": 10.0,
            "discounted_price": 12.0,
        },
        headers=headers,
    )

    assert response.status_code == 422


def test_quantity_must_be_at_least_one(client, register, create_restaurant):
    _, headers = register()
    create_restaurant(headers)

    response = client.post(
        "/api/surplus",
        json={
            "description": "Nothing, apparently",
            "quantity": 0,
            "original_price": 5.0,
        },
        headers=headers,
    )

    assert response.status_code == 422


def test_the_market_lists_only_food_that_can_still_be_rescued(
    client, listing, set_surplus_expiry
):
    headers, _, expired = listing(description="Yesterday's bread")
    _, _, live = listing(description="Tonight's pasta")

    set_surplus_expiry(
        expired["surplus_id"], datetime.now(timezone.utc) - timedelta(hours=1)
    )

    rescueable = {
        row["surplus_id"]
        for row in client.get("/api/surplus", headers=headers).json()
    }
    assert live["surplus_id"] in rescueable
    assert expired["surplus_id"] not in rescueable

    # The restaurant's own history keeps it; the browsing screen just does not
    # offer food that has already gone over.
    everything = {
        row["surplus_id"]
        for row in client.get(
            "/api/surplus?available_only=false", headers=headers
        ).json()
    }
    assert expired["surplus_id"] in everything


# --------------------------------------------------------------------------
# Reserving
# --------------------------------------------------------------------------


def test_reserving_requires_an_organization(client, listing):
    owner_headers, _, surplus = listing()

    response = reserve(client, owner_headers, surplus["surplus_id"], 1)

    assert response.status_code == 403
    assert response.json()["detail"] == "Must be an organization"


def test_verification_opens_the_reserve_path(
    client, register, create_organization, listing, admin_user
):
    """The gate and its key, in one test: pending cannot reserve, verifying can."""
    _, owner_headers = register()
    organization = create_organization(owner_headers)
    _, _, surplus = listing(quantity=3)

    refused = reserve(client, owner_headers, surplus["surplus_id"], 1)
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Organization must be verified by admin"

    _, admin_headers = admin_user()
    verified = client.put(
        f"/api/admin/organizations/{organization['org_id']}/verify",
        headers=admin_headers,
    )
    assert verified.status_code == 200, verified.text

    reserved = reserve(client, owner_headers, surplus["surplus_id"], 1)
    assert reserved.status_code == 200, reserved.text
    assert reserved.json()["quantity_remaining"] == 2


def test_reserving_requires_a_verified_organization(client, listing, organization):
    _, headers, _ = organization(verified=False)
    _, _, surplus = listing()

    response = reserve(client, headers, surplus["surplus_id"], 1)

    assert response.status_code == 403
    assert response.json()["detail"] == "Organization must be verified by admin"


def test_a_partial_reservation_leaves_the_rest_on_the_shelf(
    client, listing, organization
):
    _, headers, _ = organization()
    _, _, surplus = listing(quantity=5)

    response = reserve(client, headers, surplus["surplus_id"], 2)

    assert response.status_code == 200, response.text
    assert response.json()["quantity_reserved"] == 2
    assert response.json()["quantity_remaining"] == 3
    assert response.json()["delivery_id"].startswith("sdel_")

    after = client.get("/api/surplus", headers=headers).json()
    row = next(r for r in after if r["surplus_id"] == surplus["surplus_id"])
    assert row["quantity"] == 3
    assert row["is_available"] is True
    assert row["reserved_by_org_id"] is None

    mine = client.get("/api/surplus/reservations", headers=headers).json()
    reservation = next(
        r for r in mine if r["surplus_id"] == surplus["surplus_id"]
    )
    assert reservation["quantity"] == 2
    assert reservation["delivery_status"] == "pending"
    assert reservation["delivery_id"] == response.json()["delivery_id"]


def test_the_last_portion_closes_the_listing(client, listing, organization):
    _, headers, organization_record = organization()
    _, _, surplus = listing(quantity=3)

    response = reserve(client, headers, surplus["surplus_id"])

    assert response.status_code == 200, response.text
    assert response.json()["quantity_remaining"] == 0

    live = client.get("/api/surplus", headers=headers).json()
    assert surplus["surplus_id"] not in {row["surplus_id"] for row in live}

    everything = client.get(
        "/api/surplus?available_only=false", headers=headers
    ).json()
    row = next(r for r in everything if r["surplus_id"] == surplus["surplus_id"])
    assert row["quantity"] == 0
    assert row["is_available"] is False
    assert row["reserved_by_org_id"] == organization_record["org_id"]


def test_two_organizations_split_a_listing_and_each_sees_its_own_portion(
    client, listing, organization
):
    _, first_headers, first_org = organization(name="First Pantry")
    _, second_headers, second_org = organization(name="Second Pantry")
    _, _, surplus = listing(quantity=10)

    first = reserve(client, first_headers, surplus["surplus_id"], 6)
    second = reserve(client, second_headers, surplus["surplus_id"], 4)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["quantity_remaining"] == 0

    def reserved(headers):
        rows = client.get("/api/surplus/reservations", headers=headers).json()
        return next(
            row for row in rows if row["surplus_id"] == surplus["surplus_id"]
        )

    assert reserved(first_headers)["quantity"] == 6
    assert reserved(second_headers)["quantity"] == 4

    everything = client.get(
        "/api/surplus?available_only=false", headers=first_headers
    ).json()
    row = next(r for r in everything if r["surplus_id"] == surplus["surplus_id"])
    # Whoever took the last portion is the one whose badge the listing shows,
    # but each organization's own total is still its own.
    assert row["reserved_by_org_id"] == second_org["org_id"]
    assert row["reserved_by_org_id"] != first_org["org_id"]


def test_cannot_reserve_more_than_is_left(client, listing, organization):
    _, headers, _ = organization()
    _, _, surplus = listing(quantity=5)

    too_many = reserve(client, headers, surplus["surplus_id"], 6)
    assert too_many.status_code == 409
    assert too_many.json()["detail"] == "Only 5 portion(s) available"

    assert reserve(client, headers, surplus["surplus_id"], 4).status_code == 200
    stale = reserve(client, headers, surplus["surplus_id"], 2)
    assert stale.status_code == 409
    assert stale.json()["detail"] == "Only 1 portion(s) available"

    after = client.get("/api/surplus", headers=headers).json()
    row = next(r for r in after if r["surplus_id"] == surplus["surplus_id"])
    assert row["quantity"] == 1


def test_an_expired_listing_cannot_be_reserved(
    client, listing, organization, set_surplus_expiry
):
    _, headers, _ = organization()
    _, _, surplus = listing()

    set_surplus_expiry(
        surplus["surplus_id"], datetime.now(timezone.utc) - timedelta(minutes=1)
    )

    response = reserve(client, headers, surplus["surplus_id"], 1)

    assert response.status_code == 409
    assert response.json()["detail"] == "Surplus listing has expired"


def test_unknown_listing_is_a_404(client, organization):
    _, headers, _ = organization()

    response = reserve(client, headers, "surplus_does_not_exist", 1)

    assert response.status_code == 404
    assert response.json()["detail"] == "Surplus food not found"


def test_reservations_are_private_to_organizations(client, register):
    _, headers = register()

    response = client.get("/api/surplus/reservations", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Must be an organization"


# --------------------------------------------------------------------------
# Volunteering
# --------------------------------------------------------------------------


def volunteer_run(client, org_headers, surplus_id, quantity=None):
    """Reserve, then return the delivery the driver board is offered."""
    response = reserve(client, org_headers, surplus_id, quantity)
    assert response.status_code == 200, response.text
    return response.json()["delivery_id"]


def board(client, headers):
    response = client.get("/api/drivers/surplus-deliveries", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_reservation_puts_a_volunteer_run_on_the_board(
    client, listing, organization, register_driver
):
    _, org_headers, org = organization(name="Harbor Pantry")
    _, _, surplus = listing(quantity=5)
    delivery_id = volunteer_run(client, org_headers, surplus["surplus_id"], 2)

    _, driver_headers, _ = register_driver()
    offered = board(client, driver_headers)
    run = next(row for row in offered if row["delivery_id"] == delivery_id)

    assert run["surplus_id"] == surplus["surplus_id"]
    assert run["restaurant_name"] == "Surplus Kitchen"
    assert run["org_name"] == "Harbor Pantry"
    assert run["quantity"] == 2
    assert run["status"] == "pending"
    # A run nobody has taken shows the shape of the work, not either address.
    assert run["pickup"] is None
    assert run["dropoff"] is None
    assert run["distance_km"] is not None
    assert run["estimated_time"] > 0
    assert org["org_id"]


def test_claiming_a_run_hands_over_both_addresses(
    client, listing, organization, register_driver
):
    _, org_headers, _ = organization()
    _, _, surplus = listing(quantity=5)
    delivery_id = volunteer_run(client, org_headers, surplus["surplus_id"], 2)

    _, driver_headers, _ = register_driver()
    claimed = client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=driver_headers,
    )

    assert claimed.status_code == 200, claimed.text
    run = claimed.json()
    assert run["status"] == "assigned"
    assert run["pickup"]["address"] == "1 Test St"
    assert run["pickup"]["city"] == "NYC"
    assert run["dropoff"]["address"] == "2 Org Ave"
    assert run["dropoff"]["city"] == "NYC"

    # It is no longer on offer, and the organization's view knows who has it.
    offered = {row["delivery_id"] for row in board(client, driver_headers)}
    assert delivery_id not in offered

    reservations = client.get(
        "/api/surplus/reservations", headers=org_headers
    ).json()
    mine = next(row for row in reservations if row["delivery_id"] == delivery_id)
    assert mine["delivery_status"] == "assigned"


def test_two_volunteers_cannot_take_the_same_run(
    client, listing, organization, register_driver
):
    _, org_headers, _ = organization()
    _, _, surplus = listing()
    delivery_id = volunteer_run(client, org_headers, surplus["surplus_id"], 1)

    _, first_headers, _ = register_driver()
    _, second_headers, _ = register_driver()

    first = client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}", json={}, headers=first_headers
    )
    second = client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}", json={}, headers=second_headers
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "Delivery already taken by another volunteer"


def test_the_board_is_empty_while_the_driver_is_offline(
    client, listing, organization, register_driver
):
    _, org_headers, _ = organization()
    _, _, surplus = listing()
    delivery_id = volunteer_run(client, org_headers, surplus["surplus_id"], 1)

    _, driver_headers, _ = register_driver()
    offline = client.put(
        "/api/drivers/availability?is_available=false", headers=driver_headers
    )
    assert offline.status_code == 200

    assert delivery_id not in {row["delivery_id"] for row in board(client, driver_headers)}


def test_the_run_is_quoted_on_the_volunteers_own_vehicle(
    client, listing, organization, register_driver
):
    _, org_headers, _ = organization()
    _, _, surplus = listing()
    delivery_id = volunteer_run(client, org_headers, surplus["surplus_id"], 1)

    _, car_headers, _ = register_driver(vehicle_type="car")
    _, walk_headers, _ = register_driver(vehicle_type="walk")

    def estimate(headers):
        return next(
            row["estimated_time"]
            for row in board(client, headers)
            if row["delivery_id"] == delivery_id
        )

    walking = estimate(walk_headers)
    driving = estimate(car_headers)
    assert walking > driving > 0


def advance(client, headers, delivery_id, status):
    return client.put(
        f"/api/drivers/surplus-deliveries/{delivery_id}/status?status={status}",
        headers=headers,
    )


def active_runs(client, headers):
    response = client.get("/api/drivers/active-surplus", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_volunteer_walks_a_run_to_delivered_and_the_counters_follow(
    client, listing, organization, register_driver, scalar
):
    """The rescue is only complete when the food arrives and somebody counts it."""
    _, org_headers, org = organization()
    _, restaurant, surplus = listing(quantity=5)
    delivery_id = volunteer_run(client, org_headers, surplus["surplus_id"], 2)

    _, driver_headers, _ = register_driver()
    claimed = client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=driver_headers,
    )
    assert claimed.status_code == 200, claimed.text

    # A reload finds the run in hand, with both addresses, and not on the board.
    mine = active_runs(client, driver_headers)
    assert [row["delivery_id"] for row in mine] == [delivery_id]
    assert mine[0]["status"] == "assigned"
    assert mine[0]["pickup"]["address"] == "1 Test St"
    assert mine[0]["dropoff"]["address"] == "2 Org Ave"
    assert delivery_id not in {row["delivery_id"] for row in board(client, driver_headers)}

    # Nothing is counted while the food is still on the road.
    assert scalar("select total_received from organizations where org_id = ?", (org["org_id"],)) == 0
    assert scalar(
        "select total_meals_donated from restaurants where restaurant_id = ?",
        (restaurant["restaurant_id"],),
    ) == 0

    picked_up = advance(client, driver_headers, delivery_id, "picked_up")
    assert picked_up.status_code == 200, picked_up.text
    assert picked_up.json()["status"] == "picked_up"
    assert scalar(
        "select picked_up_at from surplus_deliveries where delivery_id = ?",
        (delivery_id,),
    )

    in_transit = advance(client, driver_headers, delivery_id, "in_transit")
    assert in_transit.status_code == 200, in_transit.text
    assert in_transit.json()["status"] == "in_transit"

    delivered = advance(client, driver_headers, delivery_id, "delivered")
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "delivered"
    assert scalar(
        "select delivered_at from surplus_deliveries where delivery_id = ?",
        (delivery_id,),
    )

    # Off the driver's plate, marked delivered for the organization, and counted
    # once on both sides of the rescue.
    assert active_runs(client, driver_headers) == []
    reservations = client.get("/api/surplus/reservations", headers=org_headers).json()
    reservation = next(row for row in reservations if row["delivery_id"] == delivery_id)
    assert reservation["delivery_status"] == "delivered"
    assert scalar("select total_received from organizations where org_id = ?", (org["org_id"],)) == 2
    assert scalar(
        "select total_meals_donated from restaurants where restaurant_id = ?",
        (restaurant["restaurant_id"],),
    ) == 2

    # A retried complete request is refused and does not count the portions
    # again.
    again = advance(client, driver_headers, delivery_id, "delivered")
    assert again.status_code == 409
    assert scalar("select total_received from organizations where org_id = ?", (org["org_id"],)) == 2
    assert scalar(
        "select total_meals_donated from restaurants where restaurant_id = ?",
        (restaurant["restaurant_id"],),
    ) == 2


def test_only_the_volunteer_carrying_a_run_can_advance_it(
    client, listing, organization, register_driver, scalar
):
    _, org_headers, _ = organization()
    _, _, surplus = listing()
    delivery_id = volunteer_run(client, org_headers, surplus["surplus_id"], 1)

    _, carrier, _ = register_driver()
    assert client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=carrier,
    ).status_code == 200

    _, bystander, _ = register_driver()
    refused = advance(client, bystander, delivery_id, "picked_up")

    assert refused.status_code == 403
    assert refused.json()["detail"] == "Not your delivery"
    assert (
        scalar(
            "select status from surplus_deliveries where delivery_id = ?",
            (delivery_id,),
        )
        == "assigned"
    )


def test_a_run_cannot_skip_the_pickup(
    client, listing, organization, register_driver, scalar
):
    """Delivering food nobody collected is not a step the API will take."""
    _, org_headers, org = organization()
    _, _, surplus = listing()
    delivery_id = volunteer_run(client, org_headers, surplus["surplus_id"], 1)

    _, driver_headers, _ = register_driver()
    assert client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=driver_headers,
    ).status_code == 200

    skipped = advance(client, driver_headers, delivery_id, "delivered")

    assert skipped.status_code == 409
    assert "next step is picked_up" in skipped.json()["detail"]
    assert (
        scalar(
            "select status from surplus_deliveries where delivery_id = ?",
            (delivery_id,),
        )
        == "assigned"
    )
    assert scalar("select total_received from organizations where org_id = ?", (org["org_id"],)) == 0


def test_a_volunteer_can_return_a_run_to_the_pool_before_pickup(
    client, listing, organization, register_driver, scalar
):
    """A changed afternoon should not strand a run nobody else can see."""
    _, org_headers, org = organization()
    _, _, surplus = listing()
    delivery_id = volunteer_run(client, org_headers, surplus["surplus_id"], 1)

    driver, driver_headers, _ = register_driver()
    assert client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=driver_headers,
    ).status_code == 200
    assert [row["delivery_id"] for row in active_runs(client, driver_headers)] == [
        delivery_id
    ]

    abandoned = client.post(
        f"/api/drivers/surplus-deliveries/{delivery_id}/abandon",
        headers=driver_headers,
    )

    assert abandoned.status_code == 200, abandoned.text
    assert abandoned.json()["status"] == "pending"
    # The caller is no longer carrying it, so neither address comes back.
    assert abandoned.json()["pickup"] is None
    assert abandoned.json()["dropoff"] is None
    assert active_runs(client, driver_headers) == []
    assert (
        scalar(
            "select status from surplus_deliveries where delivery_id = ?",
            (delivery_id,),
        )
        == "pending"
    )
    assert (
        scalar(
            "select driver_id from surplus_deliveries where delivery_id = ?",
            (delivery_id,),
        )
        is None
    )
    assert (
        scalar(
            "select assigned_at from surplus_deliveries where delivery_id = ?",
            (delivery_id,),
        )
        is None
    )
    # Nothing was delivered, so nothing is counted.
    assert scalar("select total_received from organizations where org_id = ?", (org["org_id"],)) == 0

    # It is on the board again, and another volunteer can take it.
    _, other_headers, _ = register_driver()
    assert delivery_id in {
        row["delivery_id"] for row in board(client, other_headers)
    }
    reclaimed = client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=other_headers,
    )
    assert reclaimed.status_code == 200, reclaimed.text

    # A second abandon from the original volunteer no longer owns the run and
    # is refused rather than releasing somebody else's claim.
    again = client.post(
        f"/api/drivers/surplus-deliveries/{delivery_id}/abandon",
        headers=driver_headers,
    )
    assert again.status_code == 403
    assert again.json()["detail"] == "Not your delivery"


def test_a_collected_run_cannot_be_abandoned(
    client, listing, organization, register_driver, scalar
):
    """The food is in the volunteer's hands, so it cannot go back on the board."""
    _, org_headers, _ = organization()
    _, _, surplus = listing()
    delivery_id = volunteer_run(client, org_headers, surplus["surplus_id"], 1)

    driver, driver_headers, _ = register_driver()
    assert client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=driver_headers,
    ).status_code == 200
    assert advance(client, driver_headers, delivery_id, "picked_up").status_code == 200

    refused = client.post(
        f"/api/drivers/surplus-deliveries/{delivery_id}/abandon",
        headers=driver_headers,
    )

    assert refused.status_code == 409
    assert "collected" in refused.json()["detail"].lower()
    assert (
        scalar(
            "select status from surplus_deliveries where delivery_id = ?",
            (delivery_id,),
        )
        == "picked_up"
    )
    assert (
        scalar(
            "select driver_id from surplus_deliveries where delivery_id = ?",
            (delivery_id,),
        )
        is not None
    )


def test_only_the_volunteer_carrying_a_run_can_abandon_it(
    client, listing, organization, register_driver
):
    _, org_headers, _ = organization()
    _, _, surplus = listing()
    delivery_id = volunteer_run(client, org_headers, surplus["surplus_id"], 1)

    _, carrier, _ = register_driver()
    assert client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=carrier,
    ).status_code == 200

    _, bystander, _ = register_driver()
    refused = client.post(
        f"/api/drivers/surplus-deliveries/{delivery_id}/abandon",
        headers=bystander,
    )

    assert refused.status_code == 403
    assert refused.json()["detail"] == "Not your delivery"


def test_abandoning_an_unknown_run_is_a_404(client, register_driver):
    _, headers, _ = register_driver()

    response = client.post(
        "/api/drivers/surplus-deliveries/sdel_missing/abandon", headers=headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Surplus delivery not found"


def test_active_surplus_needs_a_driver_record(client, register):
    _, headers = register()

    response = client.get("/api/drivers/active-surplus", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Driver not found"


def test_an_unknown_run_is_a_404(client, register_driver):
    _, headers, _ = register_driver()

    response = client.post(
        "/api/drivers/volunteer-surplus/sdel_missing", json={}, headers=headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Surplus delivery not found"


def test_the_board_requires_a_driver(client, register):
    _, headers = register()

    response = client.get("/api/drivers/surplus-deliveries", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Driver not found"
