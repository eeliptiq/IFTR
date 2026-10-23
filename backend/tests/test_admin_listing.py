"""The admin console's read models: accounts and organizations.

These two endpoints exist so the console can make decisions: a role change
needs the account, and verifying a food bank needs more than its name. The
tests pin the safe shape of the first and the extra context of the second.
"""


def test_listing_accounts_returns_the_safe_shape(
    client, register, admin_user
):
    target, _ = register()
    _, admin_headers = admin_user()

    response = client.get("/api/admin/users", headers=admin_headers)

    assert response.status_code == 200, response.text
    rows = response.json()
    row = next(item for item in rows if item["user_id"] == target["user_id"])
    assert row["email"] == target["email"]
    assert row["role"] == "customer"
    assert row["is_active"] is True
    assert row["is_approved"] is True
    # No row may carry credential material, whatever the database holds.
    for item in rows:
        assert not {"password", "password_hash", "hashed_password"} & set(item)


def test_accounts_can_be_filtered_by_role(client, register, admin_user):
    customer, _ = register()
    driver, _ = register(role="driver")
    _, admin_headers = admin_user()

    drivers = client.get(
        "/api/admin/users?role=driver", headers=admin_headers
    )
    assert drivers.status_code == 200
    ids = {row["user_id"] for row in drivers.json()}
    assert driver["user_id"] in ids
    assert customer["user_id"] not in ids
    assert {row["role"] for row in drivers.json()} == {"driver"}

    invalid = client.get(
        "/api/admin/users?role=wizard", headers=admin_headers
    )
    assert invalid.status_code == 422


def test_listing_accounts_needs_an_administrator(client, register):
    _, headers = register()

    assert client.get("/api/admin/users", headers=headers).status_code == 403


def test_organizations_include_pending_contact_details_and_owner(
    client, register, create_organization, verify_organization, admin_user
):
    owner, owner_headers = register()
    pending = create_organization(
        owner_headers,
        name="Pending Pantry",
        contact_email="pending@example.org",
        contact_phone="555-0111",
    )
    _, verified_headers = register()
    verified = create_organization(verified_headers, name="Verified Pantry")
    verify_organization(verified["org_id"])

    _, admin_headers = admin_user()
    response = client.get("/api/admin/organizations", headers=admin_headers)

    assert response.status_code == 200, response.text
    rows = response.json()
    by_id = {row["org_id"]: row for row in rows}

    # The queue is the point: pending applications are listed before decisions
    # already made.
    flags = [row["is_verified"] for row in rows]
    assert flags == sorted(flags)

    pending_row = by_id[pending["org_id"]]
    assert pending_row["is_verified"] is False
    assert pending_row["contact_email"] == "pending@example.org"
    assert pending_row["contact_phone"] == "555-0111"
    assert pending_row["owner_email"] == owner["email"]
    assert pending_row["owner_name"] == owner["name"]
    # Coordinates stay out even here.
    assert "lat" not in pending_row and "lng" not in pending_row

    assert by_id[verified["org_id"]]["is_verified"] is True


def test_listing_organizations_needs_an_administrator(client, register):
    _, headers = register()

    assert client.get("/api/admin/organizations", headers=headers).status_code == 403
