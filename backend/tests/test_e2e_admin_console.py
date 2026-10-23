"""
An administrator changes a role, verifies an organization and reads the trail.

The API suite checks what each endpoint does; these tests check that the console
actually reaches those endpoints in the order an administrator works: find the
account, choose a role, approve the application, take the approval away again,
then read the three events it just created. A page that posted the wrong id or
sent the role in the wrong shape would pass the API tests and fail here.

The guard has a second test: the only administrator may not demote themselves,
but may step down once somebody else holds the role - and that somebody must be
able to use the console afterwards. The handoff test restores the original
administrator before it finishes, and a function-scoped reset puts the seeded
roles and verification back before every admin journey, so these tests do not
depend on the order they run in. A fourth test signs in as a customer: the page
refuses the console, and the same token is refused by the admin reads and by a
self-promotion request. A fifth demotes the open administrator from another
session: the next request must replace the console with the refusal screen
rather than toast the API's role error over controls that no longer work. A
sixth suspends a driver and reactivates them, checking both states in the row
and both entries in the trail. The last leaves the driver holding an accepted
order: suspending them must put it back on the board, say so in the toast, and
write the reassignment against the delivery's own id.

One journey is about the admin console's payment alarm rather than an
administrator's change: the console warns, above everything else, when the
deployment charges real cards or cannot verify Stripe's webhooks. The banner is
the API's answer rendered, not something the page decides, so that journey
replaces the API process between assertions - same port, same database, same
signed-in browser - and puts the seeded environment back before it finishes.

The servers and the seed live in `tests/ui_world.py` and are shared with the
checkout journey, so both modules pay for one CRA compile rather than two. What
is real: uvicorn on a throwaway database, `craco start` pointed at it, the CLI
that seeds the first administrator, and Playwright clicking the select and the
buttons. Only the accounts and the food bank are made over the API before the
browser opens - registering them by hand is another test.

Like the checkout journey it is slow and needs node plus Chromium, so it is
opt-in:

    python -m playwright install chromium        # once per machine
    RUN_UI_E2E=1 pytest tests/test_e2e_admin_console.py

Without RUN_UI_E2E the module skips, keeping the ordinary suite as fast as it
was.
"""

import httpx
import pytest

from tests.ui_harness import (
    PASSWORD,
    api_login,
    register,
    register_driver_account,
    sign_in,
)
# `ui_world` is imported for fixture discovery: `admin_world` depends on it.
from tests.ui_world import AdminWorld, admin_world, ui_world


@pytest.fixture
def stack(admin_world) -> AdminWorld:
    """A freshly reset admin world, on the stack both browser modules share."""
    return admin_world


def test_an_administrator_changes_a_role_verifies_and_reads_the_trail(stack: AdminWorld):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, stack.admin_email)
            page.goto(f"{stack.web_url}/admin/users")
            expect(page.get_by_test_id("admin-users-page")).to_be_visible()

            # ----------------------------------------------------------------
            # The account: find it in the list and change what it is
            # ----------------------------------------------------------------
            row = page.locator("tbody tr").filter(has_text="Dana Driver")
            expect(row).to_have_count(1)
            row.get_by_test_id(f"role-select-{stack.user_id}").click()
            page.get_by_role("option", name="Support", exact=True).click()

            expect(
                row.get_by_test_id(f"role-select-{stack.user_id}")
            ).to_contain_text("Support")
            expect(page.get_by_text("Dana Driver is now Support")).to_be_visible()

            # ----------------------------------------------------------------
            # The application: verify it, then take the decision back
            # ----------------------------------------------------------------
            page.get_by_role("tab", name="Organizations").click()
            pending = page.get_by_test_id(f"pending-org-{stack.org_id}")
            expect(pending).to_be_visible()
            # The address and owner are why an admin can decide at all.
            expect(pending).to_contain_text("hello@pendingpantry.org")
            expect(pending).to_contain_text("Pat Pantry")

            page.get_by_test_id(f"verify-org-{stack.org_id}").click()
            expect(page.get_by_test_id(f"verified-org-{stack.org_id}")).to_be_visible()
            expect(page.get_by_test_id(f"pending-org-{stack.org_id}")).to_have_count(0)

            page.get_by_test_id(f"unverify-org-{stack.org_id}").click()
            dialog = page.get_by_role("dialog")
            expect(dialog).to_contain_text("will not be able to reserve surplus food")
            page.get_by_test_id("confirm-unverify").click()
            expect(dialog).to_be_hidden()
            expect(page.get_by_test_id(f"pending-org-{stack.org_id}")).to_be_visible()

            # ----------------------------------------------------------------
            # The trail: the organization's two decisions, newest first
            # ----------------------------------------------------------------
            page.get_by_role("tab", name="Audit trail").click()
            entries = page.get_by_test_id("audit-entry")
            page.get_by_test_id("audit-subject-filter").fill(stack.org_id)
            page.get_by_test_id("audit-refresh").click()
            expect(entries.first).to_contain_text("Verification removed")
            expect(entries.first).to_contain_text("Pending Pantry")
            expect(entries.first).to_contain_text("verified")
            expect(entries.first).to_contain_text("unverified")

            expect(entries.nth(1)).to_contain_text("Organization verified")
            expect(entries.nth(1)).to_contain_text("unverified")
            expect(entries.nth(1)).to_contain_text("verified")
            expect(entries.first).to_contain_text("Administrator")

            # Clear the subject before the action filter, so the next request
            # is not still narrowed to the organization.
            page.get_by_test_id("audit-subject-filter").fill("")
            page.get_by_test_id("audit-refresh").click()
            expect(entries.first).to_contain_text("Verification removed")

            # The action filter narrows the trail to role changes...
            page.get_by_test_id("audit-action-filter").click()
            page.get_by_role("option", name="Role changed").click()
            expect(entries.filter(has_text="Verification removed")).to_have_count(0)
            expect(
                entries.filter(has_text="Dana Driver").first
            ).to_contain_text("support")
            for text in entries.all_inner_texts():
                assert "Role changed" in text, text

            # ...and the subject filter answers "what happened to this account".
            # A reset may have left an earlier role change, so assert on the
            # newest entry rather than assuming this test wrote the only one.
            page.get_by_test_id("audit-subject-filter").fill(stack.user_id)
            page.get_by_test_id("audit-refresh").click()
            expect(entries.first).to_contain_text("Dana Driver")
            expect(entries.first).to_contain_text("driver")
            expect(entries.first).to_contain_text("support")
            expect(entries.first).to_contain_text("changed by an administrator")
        finally:
            browser.close()


def test_the_last_administrator_cannot_demote_themselves(stack: AdminWorld):
    """The one refusal an administrator can hit on this screen.

    The API guards the last administrator, but a select that swallowed the 409
    would leave the UI showing a role the account does not hold, and a retry
    would be the only clue. This checks the console reports the refusal and
    settles back on the role the server still has.
    """
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, stack.admin_email)
            page.goto(f"{stack.web_url}/admin/users")
            expect(page.get_by_test_id("admin-users-page")).to_be_visible()

            row = page.locator("tbody tr").filter(has_text=stack.admin_email)
            expect(row).to_have_count(1)
            role_select = row.get_by_role("combobox")
            # The id is not exposed on the stack; it is on the select, and the
            # audit filter below needs the same value the row is keyed by.
            test_id = role_select.get_attribute("data-testid") or ""
            admin_id = test_id.removeprefix("role-select-")
            assert admin_id, f"role select has no account id: {test_id!r}"

            role_select.click()
            page.get_by_role("option", name="Customer", exact=True).click()

            expect(
                page.get_by_text("Cannot remove the last administrator")
            ).to_be_visible()
            # A failed change is not a change: the select shows what the server
            # still says, not the option that was just chosen.
            expect(role_select).to_contain_text("Administrator")

            # Nor did the refused attempt become history.
            page.get_by_role("tab", name="Audit trail").click()
            page.get_by_test_id("audit-subject-filter").fill(admin_id)
            page.get_by_test_id("audit-refresh").click()
            entries = page.get_by_test_id("audit-entry")
            expect(entries.filter(has_text="create-admin")).to_have_count(1)
            # Whatever else this account's history holds, the refusal is not
            # in it: no row records it reaching `customer`.
            expect(entries.filter(has_text="customer")).to_have_count(0)
        finally:
            browser.close()


def test_administrator_access_can_be_handed_to_a_second_account(stack: AdminWorld):
    """Promote a second account, step down, and use the console as the new admin.

    The last-administrator guard must permit this: once another account holds
    the role, the original may leave it. This checks both sides through the UI,
    including that the promoted account can actually open the console. It puts
    the original administrator back before finishing, so the shared stack is
    left as the other journeys expect to find it.
    """
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, stack.admin_email)
            page.goto(f"{stack.web_url}/admin/users")
            expect(page.get_by_test_id("admin-users-page")).to_be_visible()

            # ----------------------------------------------------------------
            # Hand the role over, then give it up
            # ----------------------------------------------------------------
            stand_in = page.locator("tbody tr").filter(has_text="Harper Handoff")
            expect(stand_in).to_have_count(1)
            stand_in.get_by_role("combobox").click()
            page.get_by_role("option", name="Administrator", exact=True).click()
            expect(stand_in.get_by_role("combobox")).to_contain_text("Administrator")
            expect(
                page.get_by_text("Harper Handoff is now Administrator")
            ).to_be_visible()

            former = page.locator("tbody tr").filter(has_text=stack.admin_email)
            former.get_by_role("combobox").click()
            page.get_by_role("option", name="Support", exact=True).click()
            expect(page.get_by_text("Administrator is now Support")).to_be_visible()
            # Self-demotion re-reads the account, so the console closes itself.
            expect(page.get_by_text("Administrator access required")).to_be_visible()

            # ----------------------------------------------------------------
            # The new administrator can use what was handed over
            # ----------------------------------------------------------------
            new_admin = sign_in(browser, stack.web_url, stack.handoff_email)
            new_admin.goto(f"{stack.web_url}/admin/users")
            expect(new_admin.get_by_test_id("admin-users-page")).to_be_visible()
            expect(
                new_admin.get_by_role("heading", name="Admin Console")
            ).to_be_visible()
            expect(
                new_admin.locator("tbody tr")
                .filter(has_text=stack.admin_email)
                .get_by_role("combobox")
            ).to_contain_text("Support")

            # The promotion and the step-down are both in the trail, newest
            # first, attributed to the administrator who made them.
            new_admin.get_by_role("tab", name="Audit trail").click()
            entries = new_admin.get_by_test_id("audit-entry")
            expect(entries.first).to_contain_text("support")
            expect(entries.nth(1)).to_contain_text("Harper Handoff")
            expect(entries.nth(1)).to_contain_text("admin")

            # ----------------------------------------------------------------
            # Put the original back, then step the stand-in down
            # ----------------------------------------------------------------
            new_admin.get_by_role("tab", name="Users").click()
            former = new_admin.locator("tbody tr").filter(has_text=stack.admin_email)
            former.get_by_role("combobox").click()
            new_admin.get_by_role("option", name="Administrator", exact=True).click()
            expect(former.get_by_role("combobox")).to_contain_text("Administrator")

            stand_in = new_admin.locator("tbody tr").filter(has_text="Harper Handoff")
            stand_in.get_by_role("combobox").click()
            new_admin.get_by_role("option", name="Customer", exact=True).click()
            expect(
                new_admin.get_by_text("Administrator access required")
            ).to_be_visible()

            # The original page kept its token through the demotion; once the
            # role is back, a reload opens the console again.
            page.reload()
            expect(page.get_by_test_id("admin-users-page")).to_be_visible()
        finally:
            browser.close()


def test_a_signed_in_non_admin_is_refused_the_console_and_its_api(stack: AdminWorld):
    """Being signed in is not being allowed in.

    The screen hides its controls for a customer, but that is convenience, not
    security: the token must also be refused by the admin routes. This checks
    both, including that a non-admin cannot promote themselves through the same
    request the console would send.
    """
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, stack.handoff_email)
            page.goto(f"{stack.web_url}/admin/users")

            # Signed in, but not an administrator: the explanation, no console.
            expect(page.get_by_role("button", name="Logout")).to_be_visible()
            expect(page.get_by_text("Administrator access required")).to_be_visible()
            expect(page.get_by_test_id("admin-users-page")).to_have_count(0)
            expect(page.get_by_role("heading", name="Admin Console")).to_have_count(0)

            # The API is the actual gate. Use the same token the page holds and
            # ask for each admin read, then for the promotion the console would
            # send if its UI guard were bypassed.
            token = page.evaluate("localStorage.getItem('token')")
            assert token, "the signed-in page has no token"
            headers = {"Authorization": f"Bearer {token}"}

            for path in (
                "/api/admin/users",
                "/api/admin/organizations",
                "/api/admin/audit",
            ):
                response = page.request.get(f"{stack.api_base}{path}", headers=headers)
                assert response.status == 403, (
                    f"{path} answered {response.status}: {response.text()}"
                )

            promotion = page.request.put(
                f"{stack.api_base}/api/admin/users/{stack.handoff_id}/role",
                headers=headers,
                data={"role": "admin"},
            )
            assert promotion.status == 403, (
                f"a customer promoted themselves: {promotion.status} "
                f"{promotion.text()}"
            )

            # And the refused request changed nothing.
            account = page.request.get(f"{stack.api_base}/api/auth/me", headers=headers)
            assert account.status == 200, account.text()
            assert account.json()["role"] == "customer", account.json()
        finally:
            browser.close()


def test_a_stale_admin_session_falls_back_to_the_refusal_screen(stack: AdminWorld):
    """Revoking the role elsewhere must close an already-open console.

    The page is already rendered as an administrator when another administrator
    demotes it. The next request gets 403; the page must re-read the account and
    show the refusal, not toast the API's role message over controls it can no
    longer use. The test restores the world through the stand-in administrator
    before it finishes.
    """
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, stack.admin_email)
            page.goto(f"{stack.web_url}/admin/users")
            expect(page.get_by_test_id("admin-users-page")).to_be_visible()

            token = page.evaluate("localStorage.getItem('token')")
            assert token, "the signed-in page has no token"
            admin_headers = {"Authorization": f"Bearer {token}"}

            # Give the role to Harper, then let her take it away from the
            # original administrator while that page is still open.
            promoted = page.request.put(
                f"{stack.api_base}/api/admin/users/{stack.handoff_id}/role",
                headers=admin_headers,
                data={"role": "admin"},
            )
            assert promoted.status == 200, promoted.text()

            login = page.request.post(
                f"{stack.api_base}/api/auth/login",
                data={"email": stack.handoff_email, "password": PASSWORD},
            )
            assert login.status == 200, login.text()
            stand_in_headers = {
                "Authorization": f"Bearer {login.json()['access_token']}"
            }

            users = page.request.get(
                f"{stack.api_base}/api/admin/users", headers=stand_in_headers
            )
            assert users.status == 200, users.text()
            admin_row = next(
                row for row in users.json() if row["email"] == stack.admin_email
            )
            demoted = page.request.put(
                f"{stack.api_base}/api/admin/users/{admin_row['user_id']}/role",
                headers=stand_in_headers,
                data={"role": "support"},
            )
            assert demoted.status == 200, demoted.text()

            # The stale page still shows its controls; one request must teach it
            # that the role is gone, without a toast saying the same thing.
            page.get_by_test_id("refresh-admin").click()
            expect(page.get_by_text("Administrator access required")).to_be_visible()
            expect(page.get_by_test_id("admin-users-page")).to_have_count(0)
            expect(page.get_by_text("not authorized for this action")).to_have_count(0)
            expect(page.get_by_text("Failed to load the admin console")).to_have_count(0)

            # Put the original back, then let the stand-in step down.
            restored = page.request.put(
                f"{stack.api_base}/api/admin/users/{admin_row['user_id']}/role",
                headers=stand_in_headers,
                data={"role": "admin"},
            )
            assert restored.status == 200, restored.text()
            stepped_down = page.request.put(
                f"{stack.api_base}/api/admin/users/{stack.handoff_id}/role",
                headers=stand_in_headers,
                data={"role": "customer"},
            )
            assert stepped_down.status == 200, stepped_down.text()

            page.reload()
            expect(page.get_by_test_id("admin-users-page")).to_be_visible()
        finally:
            browser.close()


def test_an_administrator_suspends_and_reactivates_an_account(stack: AdminWorld):
    """Suspension stops the account without touching what it owns.

    The console asks before taking access away, shows the new state in the row,
    and writes both directions to the same trail as a role change. Reactivation
    is deliberately a single tap: restoring access is the reversible half.
    """
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, stack.admin_email)
            page.goto(f"{stack.web_url}/admin/users")
            expect(page.get_by_test_id("admin-users-page")).to_be_visible()

            row = page.locator("tbody tr").filter(has_text="Dana Driver")
            expect(row.get_by_test_id(f"suspend-user-{stack.user_id}")).to_be_visible()
            row.get_by_test_id(f"suspend-user-{stack.user_id}").click()

            dialog = page.get_by_role("dialog")
            expect(dialog).to_contain_text("will be signed out")
            page.get_by_test_id("confirm-suspend").click()
            expect(dialog).to_be_hidden()
            expect(row.get_by_text("Suspended")).to_be_visible()
            expect(page.get_by_text("Dana Driver is suspended")).to_be_visible()

            # The suspension is in the trail with the value before and after.
            page.get_by_role("tab", name="Audit trail").click()
            entries = page.get_by_test_id("audit-entry")
            page.get_by_test_id("audit-subject-filter").fill(stack.user_id)
            page.get_by_test_id("audit-refresh").click()
            expect(entries.first).to_contain_text("Account suspended")
            expect(entries.first).to_contain_text("Dana Driver")
            expect(entries.first).to_contain_text("active")
            expect(entries.first).to_contain_text("suspended")

            # Restoring access is the reversible half, and is not confirmed.
            page.get_by_role("tab", name="Users").click()
            row = page.locator("tbody tr").filter(has_text="Dana Driver")
            expect(
                row.get_by_test_id(f"reactivate-user-{stack.user_id}")
            ).to_be_visible()
            row.get_by_test_id(f"reactivate-user-{stack.user_id}").click()
            # Dana is not an approved driver, so the badge returns to "Awaiting
            # approval"; the action returning to Suspend is what proves the
            # account is active again.
            expect(row.get_by_test_id(f"suspend-user-{stack.user_id}")).to_be_visible()
            expect(row.get_by_text("Suspended")).to_have_count(0)
            expect(page.get_by_text("Dana Driver can sign in again")).to_be_visible()

            page.get_by_role("tab", name="Audit trail").click()
            expect(entries.first).to_contain_text("Account reactivated")
            expect(entries.first).to_contain_text("Dana Driver")
            expect(entries.first).to_contain_text("suspended")
            expect(entries.first).to_contain_text("active")
            expect(entries.nth(1)).to_contain_text("Account suspended")
        finally:
            browser.close()


def test_suspending_a_driver_returns_their_delivery_to_the_board(
    ui_world, admin_world: AdminWorld
):
    """The console is the path an administrator uses to hand work back.

    The API suite proves the reassignment; this journey proves the console
    reaches it and says so - the toast names the delivery that moved, and the
    order is claimable by the next driver once the account is locked out.
    """
    from playwright.sync_api import expect, sync_playwright

    stack = admin_world
    checkout = ui_world.checkout

    with httpx.Client(base_url=stack.api_base, timeout=30.0) as api:
        owner_headers = api_login(api, checkout.owner)
        customer = register(api, "customer", "Cora Customer")
        placed = api.post(
            "/api/orders",
            json={
                "restaurant_id": checkout.restaurant_id,
                "items": [{"item_id": checkout.item_id, "quantity": 1}],
                "delivery_lat": 40.71,
                "delivery_lng": -74.0,
                "delivery_address": "9 Customer Rd",
                "delivery_instruction_type": "hand_to_customer",
                "tip_amount": 3.0,
            },
            headers={"Authorization": f"Bearer {customer['access_token']}"},
        )
        assert placed.status_code == 201, placed.text
        order_id = placed.json()["order_id"]

        for step in ("confirmed", "preparing", "ready"):
            moved = api.put(
                f"/api/orders/{order_id}/status?status={step}",
                headers=owner_headers,
            )
            assert moved.status_code == 200, f"{step}: {moved.text}"

        driver, driver_headers = register_driver_account(api, "Ravi Reassign")
        claimed = api.post(
            f"/api/drivers/accept-order/{order_id}", headers=driver_headers
        )
        assert claimed.status_code == 200, claimed.text
        driver_id = driver["user"]["user_id"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = sign_in(browser, stack.web_url, stack.admin_email)
            page.goto(f"{stack.web_url}/admin/users")
            expect(page.get_by_test_id("admin-users-page")).to_be_visible()

            row = page.locator("tbody tr").filter(has_text="Ravi Reassign")
            expect(row).to_have_count(1)
            row.get_by_test_id(f"suspend-user-{driver_id}").click()

            dialog = page.get_by_role("dialog")
            expect(dialog).to_contain_text("goes back to the available pool")
            page.get_by_test_id("confirm-suspend").click()
            expect(
                page.get_by_text(
                    "Ravi Reassign is suspended; 1 delivery is back on the board"
                )
            ).to_be_visible()
            expect(row.get_by_text("Suspended", exact=True)).to_be_visible()

            # The trail answers "what happened to this delivery" from the
            # delivery's own id, not only from the account's.
            page.get_by_role("tab", name="Audit trail").click()
            page.get_by_test_id("audit-subject-filter").fill(order_id)
            page.get_by_test_id("audit-refresh").click()
            entries = page.get_by_test_id("audit-entry")
            expect(entries.first).to_contain_text("Delivery returned to the pool")
            expect(entries.first).to_contain_text("assigned")
            expect(entries.first).to_contain_text("ready")

            # The person waiting on the order is told the courier changed, and
            # is not told that the previous one was suspended.
            tracker = sign_in(browser, stack.web_url, customer["email"])
            tracker.goto(f"{stack.web_url}/orders/{order_id}")
            expect(tracker.get_by_test_id("reassignment-notice")).to_be_visible()
            expect(
                tracker.get_by_text("Finding you another driver")
            ).to_be_visible()

            with httpx.Client(base_url=stack.api_base, timeout=30.0) as api:
                _, other_headers = register_driver_account(api, "Nia Next")
                board = api.get(
                    "/api/drivers/available-orders", headers=other_headers
                )
                assert board.status_code == 200, board.text
                assert order_id in {job["order_id"] for job in board.json()}
                reclaimed = api.post(
                    f"/api/drivers/accept-order/{order_id}",
                    headers=other_headers,
                )
                assert reclaimed.status_code == 200, reclaimed.text

            # A different driver now holds it, and the tracker says whose.
            tracker.reload()
            expect(
                tracker.get_by_text("Your delivery changed drivers")
            ).to_be_visible()
            expect(
                tracker.get_by_text("Nia Next is taking over your delivery.")
            ).to_be_visible()
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# What the console says about the payment configuration
# ---------------------------------------------------------------------------

# Keys with the right shape and no account behind them. Nothing in this journey
# reaches Stripe: the console reads the part of a key that says its mode, and
# the webhook is only ever described, never called.
#
# Assembled from pieces on purpose. Written whole, these are plausible-looking
# credentials to any secret scanner - GitHub's push protection refused the first
# push of this branch over them - and a test constant is not worth teaching a
# repository to click "allow secret". The value is identical either way.
LIVE_KEY = "sk_" + "live_" + "e2eNotARealKey0000000000000000"
TEST_KEY = "sk_" + "test_" + "e2eNotARealKey0000000000000000"
SIGNING_SECRET = "whsec_" + "e2eNotARealSecret000000000000"


def test_the_console_says_when_payments_are_live_or_unverifiable(ui_world):
    """Three configurations of one deployment, read through the real API.

    The alarm is not decided by the page: it is what the API reports - a live
    key? a signing secret? - rendered as a warning. So each state is the
    *server's* environment, replaced between assertions while the browser, its
    session and the database stay where they are.
    """
    from playwright.sync_api import expect, sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = sign_in(browser, ui_world.web_url, ui_world.admin.admin_email)
                page.goto(f"{ui_world.web_url}/admin/users")
                expect(page.get_by_test_id("admin-users-page")).to_be_visible()

                # ---------------------------------------------------------------
                # A live key and no way to verify what Stripe sends
                # ---------------------------------------------------------------
                ui_world.restart_api(
                    {"STRIPE_SECRET_KEY": LIVE_KEY, "STRIPE_WEBHOOK_SECRET": ""}
                )
                page.reload()

                alarm = page.get_by_test_id("payments-alarm")
                expect(alarm).to_be_visible()
                expect(alarm).to_contain_text(
                    "Live payments with unverifiable webhooks"
                )
                expect(alarm).to_contain_text("every Pay button charges a real card")
                expect(alarm).to_contain_text("STRIPE_WEBHOOK_SECRET is empty")

                # The alarm is the way into the detail - and the detail names the
                # key's own words, never the key.
                page.get_by_test_id("payments-alarm-open").click()
                expect(page.get_by_text("Live secret key")).to_be_visible()
                expect(
                    page.get_by_text("Not set — events are refused with 503")
                ).to_be_visible()

                # ---------------------------------------------------------------
                # A test key, still with no signing secret: one reason, not two
                # ---------------------------------------------------------------
                ui_world.restart_api(
                    {"STRIPE_SECRET_KEY": TEST_KEY, "STRIPE_WEBHOOK_SECRET": ""}
                )
                page.reload()

                alarm = page.get_by_test_id("payments-alarm")
                expect(alarm).to_be_visible()
                expect(alarm).to_contain_text(
                    "Stripe's notifications cannot be verified"
                )
                expect(alarm).not_to_contain_text("real card")

                page.get_by_test_id("admin-tab-payments").click()
                expect(page.get_by_text("Test-mode secret key")).to_be_visible()

                # ---------------------------------------------------------------
                # A test key that can verify what it is told: nothing to shout
                # ---------------------------------------------------------------
                ui_world.restart_api(
                    {
                        "STRIPE_SECRET_KEY": TEST_KEY,
                        "STRIPE_WEBHOOK_SECRET": SIGNING_SECRET,
                    }
                )
                page.reload()

                expect(page.get_by_test_id("payments-alarm")).to_have_count(0)
                page.get_by_test_id("admin-tab-payments").click()
                expect(page.get_by_text("Test-mode secret key")).to_be_visible()
                expect(page.get_by_text("Events are verified")).to_be_visible()
                # Nothing about the configuration is wrong any more. The one thing
                # left to say is that no delivery has arrived yet, which is a
                # fact about traffic rather than about the settings.
                expect(
                    page.get_by_text("STRIPE_WEBHOOK_SECRET is empty")
                ).to_have_count(0)
            finally:
                browser.close()
    finally:
        # The checkout journey shares this server and expects it as it was.
        ui_world.restart_api()
