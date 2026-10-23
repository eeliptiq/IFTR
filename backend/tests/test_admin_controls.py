"""Admin controls: roles, account suspension and verification.

Every change is checked twice: on the wire (what the account is now) and in the
trail (who did it, and what it was before). The shared test database means the
last-administrator tests state their precondition by collapsing the admin set
first, rather than assuming how many admins earlier tests left behind.
"""



def change_role(client, headers, user_id, role):
    return client.put(
        f"/api/admin/users/{user_id}/role", json={"role": role}, headers=headers
    )


def set_active(client, headers, user_id, active):
    return client.put(
        f"/api/admin/users/{user_id}/active",
        json={"is_active": active},
        headers=headers,
    )


def audit(client, headers, **params):
    response = client.get("/api/admin/audit", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_an_administrator_can_grant_and_revoke_a_role(
    client, register, admin_user
):
    target, _ = register()
    admin, admin_headers = admin_user()

    granted = change_role(client, admin_headers, target["user_id"], "support")
    assert granted.status_code == 200, granted.text
    assert granted.json()["role"] == "support"
    assert granted.json()["email"] == target["email"]

    revoked = change_role(client, admin_headers, target["user_id"], "customer")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["role"] == "customer"

    events = audit(client, admin_headers, subject_id=target["user_id"])
    assert [(e["from_value"], e["to_value"]) for e in events] == [
        ("support", "customer"),
        ("customer", "support"),
    ]
    for event in events:
        assert event["action"] == "user.role_changed"
        assert event["subject_type"] == "user"
        assert event["actor_id"] == admin["user_id"]
        # The actor's role, not the subject's previous one.
        assert event["actor_role"] == "admin"
        assert event["actor_kind"] == "user"
        assert event["detail"] == "changed by an administrator"


def test_a_role_change_to_the_same_role_writes_nothing(
    client, register, admin_user
):
    target, _ = register()
    _, admin_headers = admin_user()

    response = change_role(client, admin_headers, target["user_id"], "customer")

    assert response.status_code == 200
    assert response.json()["role"] == "customer"
    assert audit(client, admin_headers, subject_id=target["user_id"]) == []


def test_changing_a_role_needs_an_administrator_and_a_real_account(
    client, register, admin_user
):
    target, target_headers = register()
    _, admin_headers = admin_user()

    refused = change_role(client, target_headers, target["user_id"], "driver")
    assert refused.status_code == 403

    missing = change_role(client, admin_headers, "user_does_not_exist", "driver")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "User not found"

    invalid = change_role(client, admin_headers, target["user_id"], "wizard")
    assert invalid.status_code == 422


def test_the_last_administrator_cannot_be_demoted(
    client, admin_user, scalar, execute
):
    admin, admin_headers = admin_user()

    # Leave exactly one administrator, the one about to try standing down.
    execute(
        "UPDATE users SET role = 'customer' WHERE role = 'admin' AND user_id != ?",
        (admin["user_id"],),
    )
    assert scalar("select count(*) from users where role = 'admin'") == 1

    refused = change_role(client, admin_headers, admin["user_id"], "customer")

    assert refused.status_code == 409
    assert refused.json()["detail"] == "Cannot remove the last administrator"
    assert client.get("/api/auth/me", headers=admin_headers).json()["role"] == "admin"
    assert audit(client, admin_headers, subject_id=admin["user_id"]) == []


def test_an_administrator_may_stand_down_when_another_remains(
    client, admin_user
):
    first, first_headers = admin_user()
    second, second_headers = admin_user()

    stepped_down = change_role(
        client, first_headers, first["user_id"], "customer"
    )

    assert stepped_down.status_code == 200, stepped_down.text
    assert stepped_down.json()["role"] == "customer"
    # The deployment still has an administrator, and the old token no longer
    # opens admin controls because the role is read from the database.
    assert client.get("/api/auth/me", headers=second_headers).json()["role"] == "admin"
    assert change_role(
        client, first_headers, second["user_id"], "customer"
    ).status_code == 403

    events = audit(client, second_headers, subject_id=first["user_id"])
    assert len(events) == 1
    event = events[0]
    assert (event["from_value"], event["to_value"]) == ("admin", "customer")
    assert event["actor_id"] == first["user_id"]
    assert event["actor_role"] == "admin"


def test_unverifying_blocks_new_reservations_but_keeps_existing_ones(
    client, register, create_organization, create_restaurant, admin_user
):
    _, org_headers = register()
    organization = create_organization(org_headers)
    admin, admin_headers = admin_user()
    verify_path = f"/api/admin/organizations/{organization['org_id']}/verify"

    assert client.put(verify_path, headers=admin_headers).status_code == 200

    _, owner_headers = register()
    create_restaurant(owner_headers)
    created = client.post(
        "/api/surplus",
        json={"description": "5 portions of soup", "quantity": 5, "original_price": 40},
        headers=owner_headers,
    )
    assert created.status_code == 201, created.text
    surplus = created.json()
    reserved = client.post(
        f"/api/surplus/{surplus['surplus_id']}/reserve",
        json={"quantity": 2},
        headers=org_headers,
    )
    assert reserved.status_code == 200, reserved.text

    unverified = client.delete(verify_path, headers=admin_headers)
    assert unverified.status_code == 200, unverified.text
    assert unverified.json()["is_verified"] is False

    # Idempotent, and the second call is not another event.
    assert client.delete(verify_path, headers=admin_headers).status_code == 200

    blocked = client.post(
        f"/api/surplus/{surplus['surplus_id']}/reserve",
        json={"quantity": 1},
        headers=org_headers,
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Organization must be verified by admin"

    # The portion already promised is still promised.
    mine = client.get("/api/surplus/reservations", headers=org_headers).json()
    assert surplus["surplus_id"] in {row["surplus_id"] for row in mine}

    events = audit(client, admin_headers, subject_id=organization["org_id"])
    assert [e["action"] for e in events] == [
        "organization.unverified",
        "organization.verified",
    ]
    assert (events[0]["from_value"], events[0]["to_value"]) == (
        "verified",
        "unverified",
    )
    for event in events:
        assert event["actor_id"] == admin["user_id"]
        assert event["actor_role"] == "admin"


def test_unverification_is_admin_only(client, register, create_organization):
    _, owner_headers = register()
    organization = create_organization(owner_headers)
    path = f"/api/admin/organizations/{organization['org_id']}/verify"

    assert client.delete(path, headers=owner_headers).status_code == 403
    assert client.delete(path).status_code in (401, 403)


def test_suspending_blocks_access_and_reactivating_restores_it(
    client, register, admin_user
):
    target, target_headers = register()
    admin, admin_headers = admin_user()

    suspended = set_active(client, admin_headers, target["user_id"], False)
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["is_active"] is False
    # The token was issued before the suspension; it must stop working now.
    assert client.get("/api/auth/me", headers=target_headers).status_code == 403
    blocked = client.post(
        "/api/auth/login",
        json={"email": target["email"], "password": "passw0rd123"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Account is disabled"

    # Saying the same thing again is not another event.
    assert set_active(client, admin_headers, target["user_id"], False).status_code == 200
    events = audit(client, admin_headers, subject_id=target["user_id"])
    assert [e["action"] for e in events] == ["user.suspended"]
    event = events[0]
    assert (event["from_value"], event["to_value"]) == ("active", "suspended")
    assert event["subject_type"] == "user"
    assert event["actor_id"] == admin["user_id"]
    assert event["actor_role"] == "admin"
    assert event["actor_kind"] == "user"
    assert event["detail"] == "suspended by an administrator"

    reactivated = set_active(client, admin_headers, target["user_id"], True)
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["is_active"] is True
    # Reactivation restores the same account and token; nothing was deleted.
    assert client.get("/api/auth/me", headers=target_headers).status_code == 200
    logged_in = client.post(
        "/api/auth/login",
        json={"email": target["email"], "password": "passw0rd123"},
    )
    assert logged_in.status_code == 200, logged_in.text
    assert set_active(client, admin_headers, target["user_id"], True).status_code == 200

    events = audit(client, admin_headers, subject_id=target["user_id"])
    assert [e["action"] for e in events] == [
        "user.reactivated",
        "user.suspended",
    ]
    assert (events[0]["from_value"], events[0]["to_value"]) == (
        "suspended",
        "active",
    )
    assert events[0]["detail"] == "reactivated by an administrator"
    for event in events:
        assert event["actor_id"] == admin["user_id"]
        assert event["actor_role"] == "admin"


def test_the_last_active_administrator_cannot_be_suspended(
    client, admin_user, execute
):
    admin, admin_headers = admin_user()
    # Leave one active administrator: the account trying to suspend itself.
    execute(
        "UPDATE users SET role = 'customer' WHERE role = 'admin' AND user_id != ?",
        (admin["user_id"],),
    )

    refused = set_active(client, admin_headers, admin["user_id"], False)

    assert refused.status_code == 409
    assert refused.json()["detail"] == "Cannot suspend the last administrator"
    assert client.get("/api/auth/me", headers=admin_headers).status_code == 200
    assert audit(client, admin_headers, subject_id=admin["user_id"]) == []

    # The same account cannot leave the deployment without an administrator by
    # taking the role away either.
    demoted = change_role(client, admin_headers, admin["user_id"], "customer")
    assert demoted.status_code == 409
    assert demoted.json()["detail"] == "Cannot remove the last administrator"


def test_suspended_administrators_do_not_count_toward_the_last_admin_guard(
    client, admin_user, execute
):
    first, first_headers = admin_user()
    second, _ = admin_user()
    execute(
        "UPDATE users SET role = 'customer' WHERE role = 'admin' "
        "AND user_id NOT IN (?, ?)",
        (first["user_id"], second["user_id"]),
    )

    assert set_active(client, first_headers, second["user_id"], False).status_code == 200

    # `first` is now the only administrator who can sign in, so it may not
    # demote itself just because a suspended admin still holds the role.
    refused = change_role(client, first_headers, first["user_id"], "customer")
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Cannot remove the last administrator"

    assert set_active(client, first_headers, second["user_id"], True).status_code == 200
    stepped_down = change_role(
        client, first_headers, first["user_id"], "customer"
    )
    assert stepped_down.status_code == 200, stepped_down.text


def test_suspension_needs_an_administrator_and_a_real_account(
    client, register, admin_user
):
    target, target_headers = register()
    _, admin_headers = admin_user()

    refused = set_active(client, target_headers, target["user_id"], False)
    assert refused.status_code == 403
    # The refused request did not affect the account.
    assert client.get("/api/auth/me", headers=target_headers).status_code == 200

    missing = set_active(client, admin_headers, "user_does_not_exist", False)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "User not found"

    invalid = client.put(
        f"/api/admin/users/{target['user_id']}/active",
        json={},
        headers=admin_headers,
    )
    assert invalid.status_code == 422


# --------------------------------------------------------------------------
# Suspending a driver with work in hand
# --------------------------------------------------------------------------


def test_suspending_a_driver_returns_an_accepted_order_to_the_board(
    client, register, register_driver, create_restaurant, seed_order, admin_user, scalar
):
    """A locked-out courier must not strand a delivery nobody else can take."""
    _, owner_headers = register(role="restaurant_admin")
    restaurant = create_restaurant(owner_headers)
    order = seed_order(restaurant["restaurant_id"], status="ready")

    driver, driver_headers, _ = register_driver()
    accepted = client.post(
        f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers
    )
    assert accepted.status_code == 200, accepted.text

    admin, admin_headers = admin_user()
    suspended = set_active(client, admin_headers, driver["user_id"], False)

    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["is_active"] is False
    assert suspended.json()["released_deliveries"] == 1

    # Back in the pool: ready, nobody's, and with no stale assignment stamped
    # on it.
    order_id = order["order_id"]
    assert scalar("select status from orders where order_id = ?", (order_id,)) == "ready"
    assert scalar("select driver_id from orders where order_id = ?", (order_id,)) is None
    assert scalar("select driver_name from orders where order_id = ?", (order_id,)) == ""
    assert scalar("select assigned_at from orders where order_id = ?", (order_id,)) is None

    _, other_headers, other = register_driver()
    board = client.get("/api/drivers/available-orders", headers=other_headers).json()
    assert order_id in {job["order_id"] for job in board}
    reclaimed = client.post(
        f"/api/drivers/accept-order/{order_id}", headers=other_headers
    )
    assert reclaimed.status_code == 200, reclaimed.text

    # The reassignment is in the trail against the delivery, and the suspension
    # against the account, so either question can be answered from one filter.
    events = audit(client, admin_headers, subject_id=order_id)
    assert [event["action"] for event in events] == ["delivery.reassigned"]
    assert events[0]["subject_type"] == "order"
    assert (events[0]["from_value"], events[0]["to_value"]) == ("assigned", "ready")
    assert events[0]["actor_id"] == admin["user_id"]
    assert "suspended" in events[0]["detail"]

    account_events = audit(client, admin_headers, subject_id=driver["user_id"])
    assert account_events[0]["action"] == "user.suspended"
    assert [event["action"] for event in account_events].count("user.suspended") == 1

    # Saying it again moves nothing, and reactivation restores the account
    # without taking the delivery back from the driver who now has it.
    again = set_active(client, admin_headers, driver["user_id"], False)
    assert again.status_code == 200
    assert again.json()["released_deliveries"] == 0

    reactivated = set_active(client, admin_headers, driver["user_id"], True)
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["is_active"] is True
    assert reactivated.json()["released_deliveries"] == 0
    assert (
        scalar("select driver_id from orders where order_id = ?", (order_id,))
        == other["driver_id"]
    )


def test_the_customer_tracker_shows_the_delivery_changed_hands(
    client, register, register_driver, create_restaurant, seed_order, admin_user
):
    """The person waiting on the order is told the courier changed, not why."""
    customer, customer_headers = register(name="Cara Customer")
    _, owner_headers = register(role="restaurant_admin")
    restaurant = create_restaurant(owner_headers)
    order = seed_order(
        restaurant["restaurant_id"],
        status="ready",
        customer_id=customer["user_id"],
        customer_name=customer["name"],
    )
    order_id = order["order_id"]
    tracker = f"/api/orders/{order_id}"

    driver, driver_headers, _ = register_driver()
    assert client.post(
        f"/api/drivers/accept-order/{order_id}", headers=driver_headers
    ).status_code == 200

    # Nothing to explain while the first courier still has it.
    before = client.get(tracker, headers=customer_headers)
    assert before.status_code == 200, before.text
    assert before.json()["reassignments"] == []

    admin, admin_headers = admin_user()
    suspended = set_active(client, admin_headers, driver["user_id"], False)
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["released_deliveries"] == 1

    after = client.get(tracker, headers=customer_headers)
    assert after.status_code == 200, after.text
    body = after.json()
    assert body["status"] == "ready"
    assert body["driver_id"] is None
    assert len(body["reassignments"]) == 1
    assert body["reassignments"][0]["returned_at"]
    # The fact, not the decision: no administrator id, no suspension wording.
    assert admin["user_id"] not in after.text
    assert "suspend" not in after.text.lower()

    # The same projection rides on the customer's own order list.
    mine = client.get("/api/orders", headers=customer_headers)
    assert mine.status_code == 200, mine.text
    listed = next(row for row in mine.json() if row["order_id"] == order_id)
    assert len(listed["reassignments"]) == 1

    # A different driver takes it, and the tracker names them.
    _, other_headers = register(name="Nia Next")
    signup = client.post(
        "/api/drivers/register",
        json={"vehicle_type": "car", "license_number": "DL-NIA"},
        headers=other_headers,
    )
    assert signup.status_code == 201, signup.text
    other = signup.json()
    assert client.post(
        f"/api/drivers/accept-order/{order_id}", headers=other_headers
    ).status_code == 200

    reclaimed = client.get(tracker, headers=customer_headers).json()
    assert reclaimed["driver_id"] == other["driver_id"]
    assert reclaimed["driver_name"] == "Nia Next"
    # The history stays a history: re-claiming does not erase the return.
    assert len(reclaimed["reassignments"]) == 1


def test_a_driver_holding_the_food_cannot_be_suspended(
    client, register, register_driver, create_restaurant, seed_order, admin_user, scalar
):
    """Once the food is in hand, locking the carrier out strands the delivery."""
    _, owner_headers = register(role="restaurant_admin")
    restaurant = create_restaurant(owner_headers)
    order = seed_order(restaurant["restaurant_id"], status="ready")

    driver, driver_headers, record = register_driver()
    assert client.post(
        f"/api/drivers/accept-order/{order['order_id']}", headers=driver_headers
    ).status_code == 200
    picked_up = client.put(
        f"/api/orders/{order['order_id']}/status?status=picked_up",
        headers=driver_headers,
    )
    assert picked_up.status_code == 200, picked_up.text

    admin, admin_headers = admin_user()
    refused = set_active(client, admin_headers, driver["user_id"], False)

    assert refused.status_code == 409
    assert "collected" in refused.json()["detail"].lower()
    # The refusal is total: the account still works and the delivery is
    # untouched.
    assert client.get("/api/auth/me", headers=driver_headers).status_code == 200
    order_id = order["order_id"]
    assert scalar("select status from orders where order_id = ?", (order_id,)) == "picked_up"
    assert (
        scalar("select driver_id from orders where order_id = ?", (order_id,))
        == record["driver_id"]
    )
    account_actions = {
        event["action"]
        for event in audit(client, admin_headers, subject_id=driver["user_id"])
    }
    assert "user.suspended" not in account_actions
    assert audit(client, admin_headers, subject_id=order_id) == []


def test_suspending_a_volunteer_returns_the_run_to_the_volunteer_board(
    client,
    register,
    register_driver,
    create_restaurant,
    create_organization,
    verify_organization,
    admin_user,
    scalar,
):
    """The unpaid half of the same problem: a claimed surplus run goes back."""
    _, org_headers = register()
    organization = create_organization(org_headers)
    verify_organization(organization["org_id"])

    _, owner_headers = register(role="restaurant_admin")
    create_restaurant(owner_headers)
    listed = client.post(
        "/api/surplus",
        json={
            "description": "Two trays of lasagna",
            "quantity": 2,
            "original_price": 20.0,
        },
        headers=owner_headers,
    )
    assert listed.status_code == 201, listed.text
    surplus = listed.json()
    reserved = client.post(
        f"/api/surplus/{surplus['surplus_id']}/reserve",
        json={"quantity": 1},
        headers=org_headers,
    )
    assert reserved.status_code == 200, reserved.text
    delivery_id = reserved.json()["delivery_id"]

    driver, driver_headers, _ = register_driver()
    claimed = client.post(
        f"/api/drivers/volunteer-surplus/{delivery_id}",
        json={},
        headers=driver_headers,
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["status"] == "assigned"

    admin, admin_headers = admin_user()
    suspended = set_active(client, admin_headers, driver["user_id"], False)

    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["released_deliveries"] == 1
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

    _, other_headers, _ = register_driver()
    board = client.get("/api/drivers/surplus-deliveries", headers=other_headers).json()
    assert delivery_id in {run["delivery_id"] for run in board}

    events = audit(client, admin_headers, subject_id=delivery_id)
    assert [event["action"] for event in events] == ["delivery.reassigned"]
    assert events[0]["subject_type"] == "surplus_delivery"
    assert (events[0]["from_value"], events[0]["to_value"]) == (
        "assigned",
        "pending",
    )
    assert events[0]["actor_id"] == admin["user_id"]


def test_a_transition_racing_the_suspension_is_not_overwritten(
    client,
    register,
    register_driver,
    create_restaurant,
    seed_order,
    admin_user,
    scalar,
    monkeypatch,
):
    """A transition landing in the release window must not be overwritten.

    The driver's own status request - the food is collected - lands between the
    read of the job and the write that would return it to the pool. The release
    is a conditional UPDATE that only matches while the row is still
    `assigned`, so it misses, the leftover check finds an active job, and the
    suspension is refused instead of succeeding over a pickup that arrived
    first.

    The competing write shares the request's transaction in this test, so the
    refusal rolls it back too. What is pinned down is the contract: the release
    wrote nothing and the account was not suspended.
    """
    from sqlalchemy import update

    from app.api import admin as admin_api
    from app.models.general import OrderStatus
    from app.models.order_orm import OrderRecord

    _, owner_headers = register(role="restaurant_admin")
    restaurant = create_restaurant(owner_headers)
    order = seed_order(restaurant["restaurant_id"], status="ready")
    order_id = order["order_id"]

    driver, driver_headers, record = register_driver()
    assert client.post(
        f"/api/drivers/accept-order/{order_id}", headers=driver_headers
    ).status_code == 200

    real_read = admin_api._active_driver_jobs

    async def read_then_pick_up(db, driver_id):
        orders, runs = await real_read(db, driver_id)
        # The driver's own status request, landing after the read and before
        # the release. The order is now in hand.
        await db.execute(
            update(OrderRecord)
            .where(OrderRecord.order_id == order_id)
            .values(status=OrderStatus.PICKED_UP.value)
            .execution_options(synchronize_session=False)
        )
        return orders, runs

    monkeypatch.setattr(admin_api, "_active_driver_jobs", read_then_pick_up)

    _, admin_headers = admin_user()
    refused = set_active(client, admin_headers, driver["user_id"], False)

    assert refused.status_code == 409, refused.text
    assert "changed while suspending" in refused.json()["detail"]
    # Nothing moved: the account is still usable and the job is still the one it
    # was before the request, not returned to the pool.
    assert client.get("/api/auth/me", headers=driver_headers).status_code == 200
    assert (
        scalar("select status from orders where order_id = ?", (order_id,))
        == "assigned"
    )
    assert (
        scalar("select driver_id from orders where order_id = ?", (order_id,))
        == record["driver_id"]
    )
    account_actions = {
        event["action"]
        for event in audit(client, admin_headers, subject_id=driver["user_id"])
    }
    assert "user.suspended" not in account_actions
    assert audit(client, admin_headers, subject_id=order_id) == []
