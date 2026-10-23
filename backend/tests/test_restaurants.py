"""Restaurant registration, menus, ownership, and location privacy."""

import json

RESTAURANT = {
    "name": "Fixture Pizza",
    "description": "test",
    "cuisine_type": "italian",
    "image_url": None,
    "lat": 40.7128,
    "lng": -74.0060,
    "address": "1 Test St",
    "city": "NYC",
    "zip_code": "10001",
}


def test_creating_a_restaurant_requires_a_token(client):
    assert client.post("/api/restaurants", json=RESTAURANT).status_code == 401


def test_a_user_can_only_register_one_restaurant(client, register, create_restaurant):
    _, headers = register(role="restaurant_admin")
    create_restaurant(headers)

    second = client.post("/api/restaurants", json=RESTAURANT, headers=headers)
    assert second.status_code == 400
    assert "already" in second.json()["detail"].lower()


def test_registering_a_restaurant_promotes_the_owner(client, register, create_restaurant):
    _, headers = register()  # signs up as a plain customer
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "customer"

    create_restaurant(headers)
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "restaurant_admin"


def test_a_restaurant_appears_in_the_list_and_in_detail(client, register, create_restaurant):
    _, headers = register(role="restaurant_admin")
    created = create_restaurant(headers, name="Listed Kitchen", cuisine_type="thai")

    listed = client.get("/api/restaurants").json()
    assert created["restaurant_id"] in {entry["restaurant_id"] for entry in listed}

    detail = client.get(f"/api/restaurants/{created['restaurant_id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Listed Kitchen"
    assert detail.json()["menu"] == []


def test_an_unknown_restaurant_is_404(client):
    assert client.get("/api/restaurants/rest_does_not_exist").status_code == 404


def test_the_cuisine_filter_selects_only_that_cuisine(client, register, create_restaurant):
    _, headers = register(role="restaurant_admin")
    created = create_restaurant(headers, cuisine_type="vietnamese")

    matching = {entry["restaurant_id"] for entry in client.get("/api/restaurants?cuisine=vietnamese").json()}
    assert created["restaurant_id"] in matching

    other = {entry["restaurant_id"] for entry in client.get("/api/restaurants?cuisine=peruvian").json()}
    assert created["restaurant_id"] not in other


def test_coordinates_are_never_returned(client, register, create_restaurant):
    """Encrypting the coordinates is pointless if the API hands them back."""
    _, headers = register(role="restaurant_admin")
    created = create_restaurant(headers, lat=40.7128, lng=-74.0060)

    body = client.get(f"/api/restaurants/{created['restaurant_id']}").json()
    assert "lat" not in body and "lng" not in body

    rendered = json.dumps(body)
    assert "40.7128" not in rendered
    assert "-74.006" not in rendered


def test_coordinates_are_encrypted_at_rest(client, register, create_restaurant, scalar):
    _, headers = register(role="restaurant_admin")
    created = create_restaurant(headers, lat=40.7128, lng=-74.0060)

    key = (created["restaurant_id"],)
    stored_lat = scalar("select lat_encrypted from restaurants where restaurant_id = ?", key)
    stored_lng = scalar("select lng_encrypted from restaurants where restaurant_id = ?", key)

    assert stored_lat and stored_lng
    assert "40.7128" not in stored_lat
    assert "-74.006" not in stored_lng


def test_the_owner_can_replace_the_menu(client, register, create_restaurant):
    _, headers = register(role="restaurant_admin")
    restaurant = create_restaurant(headers)
    items = [
        {"name": "Margherita", "price": 12.5, "category": "Main Course"},
        {"name": "Garlic Bread", "price": 5.0, "category": "Appetizers", "is_surplus": True, "surplus_quantity": 3},
    ]

    response = client.put(
        f"/api/restaurants/{restaurant['restaurant_id']}/menu", json=items, headers=headers
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert [item["name"] for item in saved] == ["Margherita", "Garlic Bread"]
    assert all(item["item_id"] for item in saved)  # every item gets a stable id

    served = client.get(f"/api/restaurants/{restaurant['restaurant_id']}/menu").json()
    assert [item["item_id"] for item in served] == [item["item_id"] for item in saved]
    assert served[1]["is_surplus"] is True and served[1]["surplus_quantity"] == 3


def test_a_drink_flag_survives_the_menu_round_trip(client, register, create_restaurant):
    """
    A field the request model does not declare is dropped in silence on the way
    to storage, which is how `is_drink` never reached an order: the item model
    and the order model both had it, and the menu api did not.
    """
    _, headers = register(role="restaurant_admin")
    restaurant = create_restaurant(headers)
    items = [
        {"name": "Cola", "price": 3.0, "is_drink": True},
        {"name": "Margherita", "price": 12.5},
    ]

    saved = client.put(
        f"/api/restaurants/{restaurant['restaurant_id']}/menu", json=items, headers=headers
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()[0]["is_drink"] is True
    assert saved.json()[1]["is_drink"] is False

    served = client.get(f"/api/restaurants/{restaurant['restaurant_id']}/menu").json()
    assert served[0]["is_drink"] is True
    assert served[1]["is_drink"] is False


def test_a_sealed_drink_flag_survives_the_menu_round_trip(client, register, create_restaurant):
    """
    Packaging decides whether a courier plans around a drink, so the flag has to
    reach the order the same way is_drink does - and a fountain drink that says
    nothing stays unsealed rather than being assumed safe.
    """
    _, headers = register(role="restaurant_admin")
    restaurant = create_restaurant(headers)
    items = [
        {"name": "Bottled Water", "price": 2.0, "is_drink": True, "is_sealed": True},
        {"name": "Cola", "price": 3.0, "is_drink": True},
        {"name": "Margherita", "price": 12.5},
    ]

    saved = client.put(
        f"/api/restaurants/{restaurant['restaurant_id']}/menu", json=items, headers=headers
    )
    assert saved.status_code == 200, saved.text
    assert [item["is_sealed"] for item in saved.json()] == [True, False, False]

    served = client.get(f"/api/restaurants/{restaurant['restaurant_id']}/menu").json()
    assert [item["is_sealed"] for item in served] == [True, False, False]


def test_a_stranger_cannot_edit_someone_elses_menu(client, register, create_restaurant):
    _, owner = register(role="restaurant_admin")
    restaurant = create_restaurant(owner)

    _, stranger = register(role="restaurant_admin")
    create_restaurant(stranger)  # a real owner, just not this one

    response = client.put(
        f"/api/restaurants/{restaurant['restaurant_id']}/menu",
        json=[{"name": "Hijacked", "price": 1.0}],
        headers=stranger,
    )
    assert response.status_code == 403

    assert client.get(f"/api/restaurants/{restaurant['restaurant_id']}/menu").json() == []


def test_editing_a_menu_requires_a_token(client, register, create_restaurant):
    _, headers = register(role="restaurant_admin")
    restaurant = create_restaurant(headers)

    response = client.put(
        f"/api/restaurants/{restaurant['restaurant_id']}/menu",
        json=[{"name": "Anonymous", "price": 1.0}],
    )
    assert response.status_code == 401


def test_a_menu_item_needs_a_name(client, register, create_restaurant):
    _, headers = register(role="restaurant_admin")
    restaurant = create_restaurant(headers)

    response = client.put(
        f"/api/restaurants/{restaurant['restaurant_id']}/menu",
        json=[{"name": "", "price": 1.0}],
        headers=headers,
    )
    assert response.status_code == 422
