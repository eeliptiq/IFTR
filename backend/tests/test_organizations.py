"""Organizations: registration, the role it grants, and who may see a record.

The interesting rules are not the happy path but the two silences: coordinates
never leave the server, and a pending application is visible only to the account
that filed it. Both are asserted against the wire format, not against an
internal helper, because the wire is what the screens see.
"""

import json

import pytest

from app.core.encryption import decrypt_data


def test_registration_creates_the_record_and_promotes_the_account(
    client, register, create_organization
):
    user, headers = register()

    organization = create_organization(headers)

    assert organization["user_id"] == user["user_id"]
    assert organization["name"] == "Test Food Bank"
    assert organization["org_type"] == "food_bank"
    assert organization["city"] == "NYC"
    # Nobody has verified it; that is an admin decision, not a sign-up perk.
    assert organization["is_verified"] is False
    assert organization["total_received"] == 0

    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "organization_admin"


def test_a_second_organization_for_the_same_account_is_refused(
    client, register, create_organization
):
    _, headers = register()
    create_organization(headers)

    response = client.post(
        "/api/organizations",
        json={
            "name": "Another Pantry",
            "org_type": "shelter",
            "lat": 40.7,
            "lng": -74.0,
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "You have already registered an organization"


def test_coordinates_are_encrypted_at_rest(
    client, register, create_organization, scalar
):
    _, headers = register()
    organization = create_organization(headers, lat=40.7128, lng=-74.006)

    stored_lat, stored_lng = (
        scalar(
            "SELECT lat_encrypted FROM organizations WHERE org_id = ?",
            (organization["org_id"],),
        ),
        scalar(
            "SELECT lng_encrypted FROM organizations WHERE org_id = ?",
            (organization["org_id"],),
        ),
    )

    assert stored_lat and stored_lat != "40.7128"
    assert stored_lng and stored_lng != "-74.006"
    assert float(decrypt_data(stored_lat)) == pytest.approx(40.7128)
    assert float(decrypt_data(stored_lng)) == pytest.approx(-74.006)


def test_the_public_view_omits_coordinates_and_contact_details(
    client, register, create_organization
):
    _, headers = register()
    organization = create_organization(headers, lat=40.7128, lng=-74.006)

    serialized = json.dumps(organization)

    assert "40.7128" not in serialized
    assert "-74.006" not in serialized
    assert "lat" not in organization
    assert "lng" not in organization
    # The list is readable by every signed-in account, so it does not publish a
    # food bank's phone number and inbox for the taking.
    assert "contact_email" not in organization
    assert "contact_phone" not in organization


def test_a_pending_application_is_visible_only_to_its_owner(
    client, register, create_organization, verify_organization
):
    _, owner_headers = register()
    _, stranger_headers = register()
    organization = create_organization(owner_headers)
    org_id = organization["org_id"]

    # Verified-only is the default: a pending application is absent.
    ids = [
        row["org_id"]
        for row in client.get("/api/organizations", headers=stranger_headers).json()
    ]
    assert org_id not in ids

    # Asking for unverified records does not open the pending pile either...
    ids = [
        row["org_id"]
        for row in client.get(
            "/api/organizations?verified_only=false", headers=stranger_headers
        ).json()
    ]
    assert org_id not in ids

    # ...but the owner can see their own application, which is the page's
    # "did it go through?" question.
    mine = client.get(
        "/api/organizations?verified_only=false", headers=owner_headers
    ).json()
    assert org_id in {row["org_id"] for row in mine}
    # The response may also carry organizations other tests have verified; the
    # claim here is only that a pending record is visible to its own account and
    # to nobody else.

    # Once an admin verifies it, it is public to signed-in accounts.
    verify_organization(org_id)
    ids = [
        row["org_id"]
        for row in client.get("/api/organizations", headers=stranger_headers).json()
    ]
    assert org_id in ids


def test_detail_hides_someone_elses_pending_application(
    client, register, create_organization, verify_organization
):
    _, owner_headers = register()
    _, stranger_headers = register()
    organization = create_organization(owner_headers)
    path = f"/api/organizations/{organization['org_id']}"

    assert client.get(path, headers=owner_headers).status_code == 200

    hidden = client.get(path, headers=stranger_headers)
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "Organization not found"

    verify_organization(organization["org_id"])
    assert client.get(path, headers=stranger_headers).status_code == 200


def test_listing_requires_signing_in(client, register):
    assert client.get("/api/organizations").status_code in (401, 403)


def test_only_an_admin_can_verify_an_organization(
    client, register, create_organization, admin_user
):
    _, owner_headers = register()
    organization = create_organization(owner_headers)
    path = f"/api/admin/organizations/{organization['org_id']}/verify"

    refused = client.put(path, headers=owner_headers)
    assert refused.status_code == 403

    _, admin_headers = admin_user()
    verified = client.put(path, headers=admin_headers)
    assert verified.status_code == 200, verified.text
    assert verified.json()["is_verified"] is True

    # Idempotent: a retried tap states the same fact rather than failing.
    again = client.put(path, headers=admin_headers)
    assert again.status_code == 200
    assert again.json()["is_verified"] is True

    unknown = client.put(
        "/api/admin/organizations/org_missing/verify", headers=admin_headers
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Organization not found"

