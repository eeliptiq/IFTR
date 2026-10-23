"""
The community impact feed.

The suite shares one database, so the tests compare the feed before and after
an action rather than expecting the platform to be empty.
"""

import pytest


def stats(client, headers):
    response = client.get("/api/impact/stats", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def advance(client, headers, delivery_id, status):
    response = client.put(
        f"/api/drivers/surplus-deliveries/{delivery_id}/status?status={status}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_feed_needs_a_signed_in_caller_but_not_an_administrator(
    client, register, register_driver
):
    assert client.get("/api/impact/stats").status_code == 401

    _, customer_headers = register()
    for headers in (customer_headers, register_driver()[1]):
        body = stats(client, headers)
        # Every figure the page renders has to be present, even at zero.
        assert set(body) >= {
            "total_orders",
            "meals_delivered",
            "meals_donated",
            "active_restaurants",
            "active_drivers",
            "organizations_helped",
            "surplus_saved",
        }


def test_a_delivered_rescue_becomes_donated_meals(
    client,
    register,
    create_restaurant,
    create_organization,
    verify_organization,
    register_driver,
):
    _, owner_headers = register()
    _, org_headers = register()

    before = stats(client, owner_headers)

    _, driver_headers, _ = register_driver(license_number="DL-IMPACT")
    restaurant = create_restaurant(owner_headers, name="Impact Kitchen")
    organization = create_organization(org_headers, name="Impact Pantry")
    verify_organization(organization["org_id"])

    listing = client.post(
        "/api/surplus",
        json={
            "description": "Tray of lasagna",
            "quantity": 5,
            "original_price": 40.0,
            "discounted_price": 0.0,
            "expiry_hours": 4,
        },
        headers=owner_headers,
    )
    assert listing.status_code == 201, listing.text
    surplus_id = listing.json()["surplus_id"]

    reserved = client.post(
        f"/api/surplus/{surplus_id}/reserve",
        json={"quantity": 2},
        headers=org_headers,
    )
    assert reserved.status_code == 200, reserved.text
    delivery_id = reserved.json()["delivery_id"]

    claimed = client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=driver_headers,
    )
    assert claimed.status_code == 200, claimed.text
    for status in ("picked_up", "in_transit", "delivered"):
        advance(client, driver_headers, delivery_id, status)

    after = stats(client, owner_headers)

    # Portions booked for rescue, and portions actually received.
    assert after["surplus_saved"] - before["surplus_saved"] == 2
    assert after["meals_donated"] - before["meals_donated"] == 2
    assert after["organizations_helped"] - before["organizations_helped"] == 1
    assert after["active_restaurants"] - before["active_restaurants"] == 1
    assert after["active_drivers"] - before["active_drivers"] == 1
    # A volunteer run is not a paid order; it must not inflate the order count.
    assert after["delivered_orders"] == before["delivered_orders"]
    assert after["meals_delivered"] == before["meals_delivered"]


def test_a_reservation_counts_as_saved_before_it_is_delivered(
    client, register, create_restaurant, create_organization, verify_organization
):
    """Food spoken for is no longer going to waste; it is not a receipt yet."""
    _, owner_headers = register()
    _, org_headers = register()
    restaurant = create_restaurant(owner_headers, name="Waiting Kitchen")
    organization = create_organization(org_headers, name="Waiting Pantry")
    verify_organization(organization["org_id"])

    before = stats(client, owner_headers)
    listing = client.post(
        "/api/surplus",
        json={"description": "Bread", "quantity": 3, "expiry_hours": 4},
        headers=owner_headers,
    ).json()
    client.post(
        f"/api/surplus/{listing['surplus_id']}/reserve",
        json={"quantity": 3},
        headers=org_headers,
    )

    after = stats(client, owner_headers)
    assert after["surplus_saved"] - before["surplus_saved"] == 3
    assert after["meals_donated"] == before["meals_donated"]
    assert after["organizations_helped"] == before["organizations_helped"]


def test_only_delivered_orders_count_towards_meals_and_value(
    client, register, create_restaurant, seed_order
):
    _, headers = register()
    restaurant = create_restaurant(headers, name="Counting Kitchen")
    before = stats(client, headers)

    # The shared seed: two portions, $32.99, in whatever state is asked for.
    seed_order(restaurant["restaurant_id"], status="delivered")
    seed_order(restaurant["restaurant_id"], status="cancelled")
    seed_order(restaurant["restaurant_id"], status="preparing")

    after = stats(client, headers)

    assert after["total_orders"] - before["total_orders"] == 3
    assert after["delivered_orders"] - before["delivered_orders"] == 1
    # Neither delivered nor cancelled counts as active.
    assert after["active_orders"] - before["active_orders"] == 1
    assert after["meals_delivered"] - before["meals_delivered"] == 2
    assert after["delivered_value"] - before["delivered_value"] == pytest.approx(32.99)


def test_the_admin_dashboard_agrees_with_the_impact_feed(
    client, register, admin_user, scalar
):
    _, customer_headers = register()
    refused = client.get("/api/admin/stats", headers=customer_headers)
    assert refused.status_code == 403

    _, admin_headers = admin_user()
    response = client.get("/api/admin/stats", headers=admin_headers)
    assert response.status_code == 200, response.text
    summary = response.json()
    feed = stats(client, customer_headers)

    for field in ("total_orders", "meals_donated", "active_drivers"):
        assert summary[field] == feed[field]
    # Collected revenue is read from the payment rows, not from the orders.
    # Other modules in the same session may have paid orders, so the expected
    # number is computed from the database rather than assumed to be zero.
    expected_revenue = scalar(
        "SELECT COALESCE(SUM(o.total_amount), 0) "
        "FROM orders o JOIN order_payments p ON p.order_id = o.order_id "
        "WHERE p.payment_status = 'paid'"
    )
    assert summary["total_revenue"] == pytest.approx(round(expected_revenue, 2))
    assert summary["delivered_value"] == feed["delivered_value"]


def test_an_account_without_deliveries_still_reads_zero_not_a_demo_number(
    client, register
):
    """The page used to fall back to invented totals; the API never does."""
    _, headers = register(name="Fresh Account")
    body = stats(client, headers)

    for field in (
        "total_orders",
        "meals_delivered",
        "meals_donated",
        "surplus_saved",
    ):
        assert isinstance(body[field], int)
        assert body[field] >= 0
    assert isinstance(body["delivered_value"], float)
