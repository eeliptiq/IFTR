"""Registration, login, tokens, and what the API must never hand back."""

import uuid


def _register_payload(**overrides):
    payload = {
        "email": f"{uuid.uuid4().hex}@example.com",
        "password": "passw0rd123",
        "name": "Auth Tester",
    }
    payload.update(overrides)
    return payload


def test_register_returns_a_token_and_a_safe_user(client):
    payload = _register_payload()
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == payload["email"]
    assert body["user"]["role"] == "customer"
    # The user shape is public: no credential material of any kind.
    assert not {"password", "password_hash", "hashed_password"} & set(body["user"])


def test_register_rejects_a_duplicate_email(client):
    payload = _register_payload()
    assert client.post("/api/auth/register", json=payload).status_code == 201

    again = client.post("/api/auth/register", json=payload)
    assert again.status_code == 400
    assert "already" in again.json()["detail"].lower()


def test_register_rejects_a_short_password(client):
    response = client.post("/api/auth/register", json=_register_payload(password="short"))
    assert response.status_code == 422


def test_register_rejects_an_unknown_role(client):
    response = client.post("/api/auth/register", json=_register_payload(role="wizard"))
    assert response.status_code == 422


def test_registration_cannot_grant_an_administrator_or_support(client):
    """Signing up must not be a route to a privileged role.

    An admin is created from the server's shell; a request that asks for one is
    refused rather than quietly downgraded, so a client cannot believe it holds
    a role it was never given.
    """
    for role in ("admin", "support"):
        response = client.post("/api/auth/register", json=_register_payload(role=role))
        assert response.status_code == 422, role
        assert "create-admin" in response.text


def test_registration_still_accepts_the_participant_roles(client):
    # These are onboarding intents: the authority behind them comes from a
    # restaurant, organization or driver record, not from the role string.
    for role in ("driver", "restaurant_admin", "organization_admin"):
        response = client.post("/api/auth/register", json=_register_payload(role=role))
        assert response.status_code == 201, role
        assert response.json()["user"]["role"] == role


def test_register_only_auto_approves_customers(client):
    customer = client.post("/api/auth/register", json=_register_payload(role="customer")).json()
    owner = client.post("/api/auth/register", json=_register_payload(role="restaurant_admin")).json()

    assert customer["user"]["is_approved"] is True
    assert owner["user"]["is_approved"] is False  # owners wait for an admin


def test_login_accepts_the_right_password(client):
    payload = _register_payload()
    client.post("/api/auth/register", json=payload)

    response = client.post(
        "/api/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


def test_login_rejects_a_wrong_password(client):
    payload = _register_payload()
    client.post("/api/auth/register", json=payload)

    response = client.post(
        "/api/auth/login",
        json={"email": payload["email"], "password": "definitely-wrong"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_rejects_an_unknown_email(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "nobody-at-all@example.com", "password": "passw0rd123"},
    )
    assert response.status_code == 401


def test_a_failed_login_does_not_reveal_whether_the_account_exists(client):
    payload = _register_payload()
    client.post("/api/auth/register", json=payload)

    known = client.post("/api/auth/login", json={"email": payload["email"], "password": "nope-nope-nope"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"})

    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json()


def test_me_needs_a_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_rejects_a_garbage_token(client):
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.real.jwt"})
    assert response.status_code == 401


def test_me_returns_the_signed_in_user(client, register):
    user, headers = register()

    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["user_id"] == user["user_id"]


def test_logout_answers_even_without_a_token(client, register):
    """The button must not fail when the token it held has already expired."""
    _, headers = register()

    signed_in = client.post("/api/auth/logout", headers=headers)
    already_out = client.post("/api/auth/logout")

    assert signed_in.status_code == 200
    assert signed_in.json() == {"message": "Logged out"}
    assert already_out.status_code == 200
    assert already_out.json() == {"message": "Logged out"}


def test_passwords_are_stored_hashed_and_salted(client, scalar):
    first = _register_payload()
    second = _register_payload(password=first["password"])  # same password, different account
    client.post("/api/auth/register", json=first)
    client.post("/api/auth/register", json=second)

    stored = scalar("select password_hash from users where email = ?", (first["email"],))
    assert stored and stored != first["password"]
    assert first["password"] not in stored

    twin = scalar("select password_hash from users where email = ?", (second["email"],))
    assert twin != stored, "identical passwords must not produce identical hashes"
