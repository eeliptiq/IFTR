"""
The restaurant order queue: what an owner may see, and which status moves are
theirs to make.

The queue is two endpoints the merged React screen already calls -
`GET /api/restaurants/{id}/orders` for a tab of the board and
`PUT /api/orders/{id}/status` for the one button on each card. Both are driven
here over HTTP, and where a refusal is expected the stored row is read back to
confirm nothing moved.

The reference implementation this was ported from let any authenticated caller
set any order to any status. Most of the transition tests below exist because of
that: ownership is a fact about the restaurant, not something the caller
declares, and the restaurant only owns half of an order's lifecycle.
"""

import datetime

PENDING = "pending"
CONFIRMED = "confirmed"
PREPARING = "preparing"
READY = "ready"
DELIVERED = "delivered"
CANCELLED = "cancelled"

UTC = datetime.timezone.utc


def orders_url(restaurant_id: str) -> str:
    return f"/api/restaurants/{restaurant_id}/orders"


def status_url(order_id: str, status: str) -> str:
    return f"/api/orders/{order_id}/status?status={status}"


def stored_status(scalar, order_id: str):
    return scalar("select status from orders where order_id = ?", (order_id,))


# --------------------------------------------------------------------------
# Reading the queue
# --------------------------------------------------------------------------


def test_listing_orders_requires_a_token(client, register, create_restaurant, seed_order):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seed_order(restaurant["restaurant_id"])

    assert client.get(orders_url(restaurant["restaurant_id"])).status_code == 401


def test_the_owner_sees_the_order_the_screen_renders(
    client, register, create_restaurant, seed_order
):
    """Every field the card reads: id, status, items, and the total."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    response = client.get(orders_url(restaurant["restaurant_id"]), headers=owner)
    assert response.status_code == 200, response.text

    body = response.json()
    assert [order["order_id"] for order in body] == [seeded["order_id"]]
    assert body[0]["status"] == PENDING
    assert body[0]["total_amount"] == 32.99
    assert body[0]["is_donation"] is False
    assert body[0]["created_at"]  # the screen renders the time
    assert body[0]["items"][0]["name"] == "Margherita"
    assert body[0]["items"][0]["quantity"] == 2


def test_an_empty_queue_is_an_empty_list(client, register, create_restaurant):
    """A restaurant that has sold nothing is not a missing restaurant."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)

    response = client.get(orders_url(restaurant["restaurant_id"]), headers=owner)
    assert response.status_code == 200
    assert response.json() == []


def test_an_unknown_restaurant_is_404(client, register):
    _, headers = register(role="restaurant_admin")
    assert client.get(orders_url("rest_does_not_exist"), headers=headers).status_code == 404


def test_a_stranger_cannot_read_a_restaurants_orders(
    client, register, create_restaurant, seed_order
):
    """A queue is the restaurant's book of business, addresses included."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    _, stranger = register(role="restaurant_admin")
    create_restaurant(stranger)  # a real owner, just not this one

    response = client.get(orders_url(restaurant["restaurant_id"]), headers=stranger)
    assert response.status_code == 403
    assert seeded["order_id"] not in response.text


def test_one_restaurants_queue_holds_only_its_own_orders(
    client, register, create_restaurant, seed_order
):
    _, owner = register(role="restaurant_admin")
    mine = create_restaurant(owner, name="Mine")
    my_order = seed_order(mine["restaurant_id"])

    _, other_owner = register(role="restaurant_admin")
    theirs = create_restaurant(other_owner, name="Theirs")
    their_order = seed_order(theirs["restaurant_id"])

    body = client.get(orders_url(mine["restaurant_id"]), headers=owner).json()
    listed = [order["order_id"] for order in body]
    assert my_order["order_id"] in listed
    assert their_order["order_id"] not in listed


def test_the_status_filter_selects_only_that_tab(
    client, register, create_restaurant, seed_order
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    waiting = seed_order(restaurant["restaurant_id"], status=PENDING)
    accepted = seed_order(restaurant["restaurant_id"], status=CONFIRMED)

    pending_tab = client.get(
        f"{orders_url(restaurant['restaurant_id'])}?status={PENDING}", headers=owner
    ).json()
    assert [order["order_id"] for order in pending_tab] == [waiting["order_id"]]

    all_tab = client.get(orders_url(restaurant["restaurant_id"]), headers=owner).json()
    assert {order["order_id"] for order in all_tab} == {
        waiting["order_id"],
        accepted["order_id"],
    }


def test_an_unknown_status_filter_is_rejected(client, register, create_restaurant):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)

    response = client.get(
        f"{orders_url(restaurant['restaurant_id'])}?status=banana", headers=owner
    )
    assert response.status_code == 422


def test_the_queue_is_newest_first(client, register, create_restaurant, seed_order):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    older = seed_order(
        restaurant["restaurant_id"],
        created_at=datetime.datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    newer = seed_order(
        restaurant["restaurant_id"],
        created_at=datetime.datetime(2026, 1, 1, 13, 0, tzinfo=UTC),
    )

    body = client.get(orders_url(restaurant["restaurant_id"]), headers=owner).json()
    assert [order["order_id"] for order in body] == [newer["order_id"], older["order_id"]]


# --------------------------------------------------------------------------
# Advancing an order
# --------------------------------------------------------------------------


def test_the_owner_can_accept_a_pending_order(
    client, register, create_restaurant, seed_order
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    response = client.put(status_url(seeded["order_id"], CONFIRMED), headers=owner)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == CONFIRMED


def test_accepting_an_order_is_stamped_and_persisted(
    client, register, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    client.put(status_url(seeded["order_id"], CONFIRMED), headers=owner)

    assert stored_status(scalar, seeded["order_id"]) == CONFIRMED
    assert scalar(
        "select confirmed_at from orders where order_id = ?", (seeded["order_id"],)
    )

    relisted = client.get(orders_url(restaurant["restaurant_id"]), headers=owner).json()
    assert relisted[0]["status"] == CONFIRMED


def test_the_owner_can_walk_an_order_all_the_way_to_ready(
    client, register, create_restaurant, seed_order
):
    """The three buttons the screen offers, in the order it offers them."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    for step in (CONFIRMED, PREPARING, READY):
        response = client.put(status_url(seeded["order_id"], step), headers=owner)
        assert response.status_code == 200, f"{step}: {response.text}"
        assert response.json()["status"] == step


def test_a_cooking_order_is_stamped_ready(
    client, register, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"], status=PREPARING)

    client.put(status_url(seeded["order_id"], READY), headers=owner)

    assert stored_status(scalar, seeded["order_id"]) == READY
    assert scalar("select ready_at from orders where order_id = ?", (seeded["order_id"],))


def test_the_owner_can_decline_a_pending_order(
    client, register, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    response = client.put(status_url(seeded["order_id"], CANCELLED), headers=owner)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == CANCELLED

    assert stored_status(scalar, seeded["order_id"]) == CANCELLED
    assert scalar(
        "select cancelled_at from orders where order_id = ?", (seeded["order_id"],)
    )


def test_an_order_cannot_skip_a_step(
    client, register, create_restaurant, seed_order, scalar
):
    """Pending food is not suddenly cooked: the move is refused, and nothing moves."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    response = client.put(status_url(seeded["order_id"], READY), headers=owner)
    assert response.status_code == 409
    assert PENDING in response.json()["detail"] and READY in response.json()["detail"]

    assert stored_status(scalar, seeded["order_id"]) == PENDING


def test_the_owner_cannot_mark_food_delivered(
    client, register, create_restaurant, seed_order, scalar
):
    """Pickup and delivery belong to the driver flow, not to the kitchen."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"], status=READY)

    response = client.put(status_url(seeded["order_id"], DELIVERED), headers=owner)
    assert response.status_code == 409

    assert stored_status(scalar, seeded["order_id"]) == READY


def test_an_order_being_cooked_cannot_be_cancelled(
    client, register, create_restaurant, seed_order, scalar
):
    """Once food is being made, cancelling goes through support."""
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"], status=PREPARING)

    response = client.put(status_url(seeded["order_id"], CANCELLED), headers=owner)
    assert response.status_code == 409

    assert stored_status(scalar, seeded["order_id"]) == PREPARING


def test_a_finished_order_cannot_be_reopened(
    client, register, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"], status=DELIVERED)

    response = client.put(status_url(seeded["order_id"], PENDING), headers=owner)
    assert response.status_code == 409

    assert stored_status(scalar, seeded["order_id"]) == DELIVERED


def test_a_stranger_cannot_advance_someone_elses_order(
    client, register, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    _, stranger = register(role="restaurant_admin")
    create_restaurant(stranger)

    response = client.put(status_url(seeded["order_id"], CONFIRMED), headers=stranger)
    assert response.status_code == 403

    assert stored_status(scalar, seeded["order_id"]) == PENDING


def test_advancing_an_order_requires_a_token(client, register, create_restaurant, seed_order):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    assert client.put(status_url(seeded["order_id"], CONFIRMED)).status_code == 401


def test_an_empty_json_body_is_accepted_like_the_screen_sends(
    client, register, create_restaurant, seed_order
):
    """
    The screen sends `axios.put(url, {}, ...)`, so the exact wire format is a
    query-parameter status plus an empty JSON body. An endpoint that only
    worked without a body would look fine in a hand-run curl and fail here.
    """
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    response = client.put(
        status_url(seeded["order_id"], CONFIRMED), json={}, headers=owner
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == CONFIRMED


def test_an_unknown_order_is_404(client, register):
    _, headers = register(role="restaurant_admin")
    assert client.put(status_url("order_does_not_exist", CONFIRMED), headers=headers).status_code == 404


def test_an_order_without_a_status_is_rejected(client, register, create_restaurant, seed_order):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    response = client.put(f"/api/orders/{seeded['order_id']}/status", headers=owner)
    assert response.status_code == 422


def test_an_unknown_status_is_rejected(
    client, register, create_restaurant, seed_order, scalar
):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)
    seeded = seed_order(restaurant["restaurant_id"])

    response = client.put(status_url(seeded["order_id"], "banana"), headers=owner)
    assert response.status_code == 422

    assert stored_status(scalar, seeded["order_id"]) == PENDING


# --------------------------------------------------------------------------
# The rules themselves
# --------------------------------------------------------------------------


def test_the_derived_order_facts_are_read_from_the_items():
    """Both are computed, not stored, and both tolerate a hand-written row."""
    from app.schemas.order import OrderResponse

    assert OrderResponse.item_count_of([{"quantity": 3}, {"quantity": None}]) == 4
    assert OrderResponse.item_count_of(["junk", {"quantity": 2}]) == 3

    assert OrderResponse.has_drinks_of([{"name": "Cola", "is_drink": True}]) is True
    assert OrderResponse.has_drinks_of([{"name": "Pizza"}]) is False
    assert OrderResponse.has_drinks_of(["junk"]) is False

    # Drink count is in units, like item_count: two Cokes are two cups.
    assert OrderResponse.drink_count_of(
        [{"name": "Cola", "is_drink": True, "quantity": 2}, {"name": "Pizza"}]
    ) == 2
    assert OrderResponse.drink_count_of(
        [{"name": "Cola", "is_drink": True}, {"quantity": None, "is_drink": True}]
    ) == 2
    assert OrderResponse.drink_count_of([{"name": "Pizza", "quantity": 3}]) == 0
    assert OrderResponse.drink_count_of(["junk"]) == 0

    # Unsealed is the subset that needs planning around, and a drink with no
    # packaging flag counts as unsealed: an open cup is the case to assume.
    mixed = [
        {"name": "Cola", "is_drink": True, "quantity": 2},
        {"name": "Bottled Water", "is_drink": True, "quantity": 3, "is_sealed": True},
        {"name": "Pizza", "quantity": 2},
    ]
    assert OrderResponse.drink_count_of(mixed) == 5
    assert OrderResponse.unsealed_drink_count_of(mixed) == 2
    assert OrderResponse.unsealed_drink_count_of(
        [{"name": "Can", "is_drink": True, "is_sealed": True}]
    ) == 0
    assert OrderResponse.unsealed_drink_count_of(["junk"]) == 0
    assert OrderResponse.unsealed_drink_count_of(
        [{"name": "Cup", "is_drink": True, "quantity": None}]
    ) == 1


def test_every_status_has_a_transition_rule():
    """Adding a status to the enum without deciding its edges must not slip by."""
    from app.models.general import OrderStatus
    from app.order_flow import OrderFlowManager

    assert set(OrderFlowManager.TRANSITION_RULES) == set(OrderStatus)


def test_the_rules_never_allow_a_status_to_reach_itself():
    from app.order_flow import OrderFlowManager

    for current, allowed in OrderFlowManager.TRANSITION_RULES.items():
        assert current not in allowed, current
