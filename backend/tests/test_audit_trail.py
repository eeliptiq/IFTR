"""The audit trail: every privileged transition, once, with who made it.

The trail is read back through the admin endpoint rather than queried directly,
so these tests exercise the same shape an investigator sees. Assertions filter
by subject because the suite shares one database and other tests also promote
accounts.
"""


def audit(client, headers, **params):
    response = client.get("/api/admin/audit", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_registering_a_restaurant_records_the_role_change(
    client, register, create_restaurant, admin_user
):
    user, headers = register()
    _, admin_headers = admin_user()

    create_restaurant(headers)

    events = audit(client, admin_headers, subject_id=user["user_id"])
    assert len(events) == 1
    event = events[0]
    assert event["action"] == "user.role_changed"
    assert event["subject_type"] == "user"
    assert event["subject_id"] == user["user_id"]
    assert event["from_value"] == "customer"
    assert event["to_value"] == "restaurant_admin"
    assert event["detail"] == "registered a restaurant"
    # The actor is the account itself, and the role recorded is the one it held
    # when it acted, not the one it ended up with.
    assert event["actor_id"] == user["user_id"]
    assert event["actor_role"] == "customer"
    assert event["actor_kind"] == "user"
    assert event["created_at"].endswith(("+00:00", "Z"))


def test_driver_onboarding_records_the_transition(
    client, register_driver, admin_user
):
    user, _, _ = register_driver()
    _, admin_headers = admin_user()

    events = audit(client, admin_headers, subject_id=user["user_id"])
    assert [(e["from_value"], e["to_value"]) for e in events] == [
        ("customer", "driver")
    ]
    assert events[0]["detail"] == "registered as a driver"


def test_organization_onboarding_records_the_transition(
    client, register, create_organization, admin_user
):
    user, headers = register()
    _, admin_headers = admin_user()

    create_organization(headers)

    events = audit(client, admin_headers, subject_id=user["user_id"])
    assert [(e["from_value"], e["to_value"]) for e in events] == [
        ("customer", "organization_admin")
    ]
    assert events[0]["detail"] == "registered an organization"


def test_a_role_that_did_not_change_is_not_history(
    client, register, create_restaurant, admin_user
):
    user, headers = register(role="restaurant_admin")
    _, admin_headers = admin_user()

    create_restaurant(headers)  # already the target role

    assert audit(client, admin_headers, subject_id=user["user_id"]) == []


def test_verifying_an_organization_records_the_actor_once(
    client, register, create_organization, admin_user
):
    _, owner_headers = register()
    organization = create_organization(owner_headers)
    admin, admin_headers = admin_user()
    path = f"/api/admin/organizations/{organization['org_id']}/verify"

    assert client.put(path, headers=admin_headers).status_code == 200
    # Idempotent endpoint, but the transition happened once.
    assert client.put(path, headers=admin_headers).status_code == 200

    events = audit(client, admin_headers, subject_id=organization["org_id"])
    assert len(events) == 1
    event = events[0]
    assert event["action"] == "organization.verified"
    assert event["subject_type"] == "organization"
    assert event["from_value"] == "unverified"
    assert event["to_value"] == "verified"
    assert event["actor_id"] == admin["user_id"]
    assert event["actor_role"] == "admin"
    assert event["actor_kind"] == "user"


def test_the_trail_is_filterable_and_newest_first(
    client, register, create_restaurant, admin_user
):
    user, headers = register()
    _, admin_headers = admin_user()

    client.post(
        "/api/drivers/register",
        json={"vehicle_type": "car", "license_number": "AUDIT-1"},
        headers=headers,
    )
    create_restaurant(headers)

    events = audit(client, admin_headers, subject_id=user["user_id"])
    assert [e["to_value"] for e in events] == ["restaurant_admin", "driver"]

    only_roles = audit(
        client,
        admin_headers,
        subject_id=user["user_id"],
        action="user.role_changed",
    )
    assert len(only_roles) == 2

    organizations = audit(
        client,
        admin_headers,
        subject_id=user["user_id"],
        action="organization.verified",
    )
    assert organizations == []

    newest = audit(
        client, admin_headers, subject_id=user["user_id"], limit=1
    )
    assert [e["to_value"] for e in newest] == ["restaurant_admin"]


def test_the_trail_is_admin_only(client, register):
    _, headers = register()

    assert client.get("/api/admin/audit", headers=headers).status_code == 403
    assert client.get("/api/admin/audit").status_code in (401, 403)
