"""
Driver earnings: completed paid trips, their windows, and volunteer runs.

The suite shares one database, so each test reads the earnings of a driver it
just registered; nobody else's trips can appear on that record.
"""

from datetime import datetime, timedelta, timezone


def earnings(client, headers):
    response = client.get("/api/drivers/earnings", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_earnings_need_a_driver_record(client, register):
    _, headers = register()

    response = client.get("/api/drivers/earnings", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Driver not found"
    assert client.get("/api/drivers/earnings").status_code == 401


def test_a_new_driver_starts_at_zero(client, register_driver):
    _, headers, _ = register_driver(license_number="DL-NEW")

    body = earnings(client, headers)

    assert body["total_deliveries"] == 0
    assert body["total_earnings"] == 0.0
    assert body["surplus_runs"] == 0
    assert body["recent"] == []
    for window in ("today", "week", "month"):
        assert body[window] == {
            "deliveries": 0,
            "delivery_fees": 0.0,
            "tips": 0.0,
            "earnings": 0.0,
        }


def test_completed_trips_are_counted_by_their_delivery_time(
    client, register, register_driver, create_restaurant, seed_order
):
    _, owner_headers = register()
    restaurant = create_restaurant(owner_headers, name="Earnings Kitchen")
    _, headers, driver = register_driver(license_number="DL-EARN")
    _, other_headers, other_driver = register_driver(license_number="DL-OTHER")
    now = datetime.now(timezone.utc)

    # Today, ten days ago, forty days ago: one in each window, then outside all
    # three. The tip is part of the trip's pay.
    seeded = [
        seed_order(
            restaurant["restaurant_id"],
            status="delivered",
            driver_id=driver["driver_id"],
            delivered_at=now,
            delivery_fee=2.99,
            tip_amount=3.0,
        ),
        seed_order(
            restaurant["restaurant_id"],
            status="delivered",
            driver_id=driver["driver_id"],
            delivered_at=now - timedelta(days=10),
            delivery_fee=5.99,
            tip_amount=0.0,
        ),
        seed_order(
            restaurant["restaurant_id"],
            status="delivered",
            driver_id=driver["driver_id"],
            delivered_at=now - timedelta(days=40),
            delivery_fee=1.0,
            tip_amount=0.0,
        ),
        # Not delivered: never counted, however far along it got.
        seed_order(
            restaurant["restaurant_id"],
            status="cancelled",
            driver_id=driver["driver_id"],
            delivered_at=now,
            delivery_fee=9.0,
        ),
    ]
    # Somebody else's trip must not appear in this driver's totals.
    seed_order(
        restaurant["restaurant_id"],
        status="delivered",
        driver_id=other_driver["driver_id"],
        delivered_at=now,
        delivery_fee=7.5,
        tip_amount=5.0,
    )

    body = earnings(client, headers)

    assert body["total_deliveries"] == 3
    assert body["total_earnings"] == 12.98
    assert body["today"] == {
        "deliveries": 1,
        "delivery_fees": 2.99,
        "tips": 3.0,
        "earnings": 5.99,
    }
    assert body["week"]["deliveries"] == 1
    assert body["week"]["earnings"] == 5.99
    assert body["month"]["deliveries"] == 2
    assert body["month"]["earnings"] == 11.98

    assert [row["order_id"] for row in body["recent"]] == [
        seeded[0]["order_id"],
        seeded[1]["order_id"],
        seeded[2]["order_id"],
    ]
    assert body["recent"][0]["tips"] == 3.0
    assert body["recent"][0]["earnings"] == 5.99


def test_a_volunteer_run_is_reported_separately_from_paid_trips(
    client,
    register,
    register_driver,
    create_restaurant,
    create_organization,
    verify_organization,
):
    _, owner_headers = register()
    create_restaurant(owner_headers, name="Volunteer Kitchen")
    _, org_headers = register()
    organization = create_organization(org_headers, name="Volunteer Pantry")
    verify_organization(organization["org_id"])
    _, headers, driver = register_driver(license_number="DL-VOL")

    listing = client.post(
        "/api/surplus",
        json={"description": "Soup", "quantity": 4, "expiry_hours": 4},
        headers=owner_headers,
    ).json()
    reserved = client.post(
        f"/api/surplus/{listing['surplus_id']}/reserve",
        json={"quantity": 4},
        headers=org_headers,
    ).json()
    delivery_id = reserved["delivery_id"]

    assert client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=headers,
    ).status_code == 200
    for status in ("picked_up", "in_transit", "delivered"):
        response = client.put(
            f"/api/drivers/surplus-deliveries/{delivery_id}/status?status={status}",
            headers=headers,
        )
        assert response.status_code == 200, response.text

    body = earnings(client, headers)

    assert body["surplus_runs"] == 1
    # The rescue is real work, but it is not a paid delivery.
    assert body["total_deliveries"] == 0
    assert body["total_earnings"] == 0.0
    assert body["recent"] == []
