# IFTR (Evolved) — running locally

This is the "more features" build of the project: a self-contained FastAPI
backend (SQLite by default, PostgreSQL via `DATABASE_URL`) with the React UI
ported from the `Emergent/SharePlate-main` app.

## Layout

```
Evolved/
  backend/     FastAPI app (app/main.py) — auth, users, restaurants
  frontend/    React (CRA + craco) UI, ported from the Emergent app
```

## Backend

Requires Python 3.14 (the repo-root `.venv`). Dependencies are pinned in
[`backend/requirements.txt`](backend/requirements.txt).

```bash
cd backend
# One-time: install deps into your virtualenv
python -m pip install -r requirements.txt

# Run (finds the repo-root .venv automatically)
./run.sh                 # http://127.0.0.1:8000  •  docs at /docs
# or, explicitly:
python -m uvicorn app.main:app --reload

# Taking payments locally: API plus Stripe's event forwarder, keys from .env
./dev_payments.sh
```

All API routes are mounted under `/api`:

| Method | Path                        | Auth        | Notes                                   |
| ------ | --------------------------- | ----------- | --------------------------------------- |
| POST   | `/api/auth/register`        | –           | returns `{access_token, token_type, user}`; participant roles only |
| POST   | `/api/auth/login`           | –           | JSON `{email, password}`                |
| GET    | `/api/auth/me`              | Bearer      | current user                            |
| PUT    | `/api/users/me`             | Bearer      | update profile                          |
| GET    | `/api/restaurants`          | –           | list (optional `cuisine`)               |
| POST   | `/api/restaurants`          | Bearer      | register a restaurant (promotes role)   |
| GET    | `/api/restaurants/{id}`     | –           | detail incl. menu                       |
| GET    | `/api/restaurants/{id}/menu`| –           | menu items                              |
| PUT    | `/api/restaurants/{id}/menu`| Bearer      | replace menu (owner only)               |
| GET    | `/api/restaurants/{id}/orders` | Bearer   | that restaurant's queue, newest first; optional `status` (owner only) |
| POST   | `/api/orders`               | Bearer      | place an order (checkout); priced from the menu |
| GET    | `/api/orders`               | Bearer      | the caller's own orders, newest first; optional `status` |
| GET    | `/api/orders/{id}`          | Bearer      | one order: its customer, its restaurant's owner or its driver; carries any `reassignments` |
| POST   | `/api/orders/{id}/add-tip`  | Bearer      | customer adds a tip (increases only)     |
| POST   | `/api/orders/{id}/report-issue` | Bearer   | customer reports a problem              |
| PUT    | `/api/orders/{id}/status?status=` | Bearer | advance an order (its restaurant, its driver, or the customer cancelling) |
| POST   | `/api/payments/checkout`     | Bearer      | open hosted Stripe Checkout for one of your orders; `503` when no Stripe key is configured |
| GET    | `/api/payments/status/{session_id}` | Bearer | that payment's state, refreshed from Stripe |
| POST   | `/api/payments/webhook`      | Stripe signature | Checkout completed / expired / async outcome |
| GET    | `/api/payments/diagnostics`  | Bearer (admin) | which Stripe settings are active and when a webhook last arrived; never a key |
| POST   | `/api/drivers/register`     | Bearer      | sign up as a driver (promotes role)     |
| GET    | `/api/drivers/profile`      | Bearer      | own driver record; `404` `Driver not found` if none |
| PUT    | `/api/drivers/vehicle`      | Bearer      | change vehicle (and licence, if sent)   |
| PUT    | `/api/drivers/availability?is_available=` | Bearer | go online / offline          |
| GET    | `/api/drivers/available-orders` | Bearer   | cooked, unclaimed orders, oldest first  |
| POST   | `/api/drivers/accept-order/{id}` | Bearer  | claim one                               |
| GET    | `/api/drivers/active-delivery` | Bearer   | the job in hand, or `null`              |
| GET    | `/api/drivers/surplus-deliveries` | Bearer | volunteer surplus runs nobody has taken |
| POST   | `/api/drivers/volunteer-surplus/{id}` | Bearer | take one of those runs             |
| GET    | `/api/drivers/active-surplus` | Bearer | the volunteer runs the caller has claimed and not finished |
| PUT    | `/api/drivers/surplus-deliveries/{id}/status?status=` | Bearer | picked up, in transit, delivered |
| POST   | `/api/drivers/surplus-deliveries/{id}/abandon` | Bearer | return an uncollected run to the pool |
| POST   | `/api/organizations`        | Bearer      | register a food bank / shelter (promotes role) |
| GET    | `/api/organizations`        | Bearer      | verified organizations; `verified_only=false` adds your own pending one |
| GET    | `/api/organizations/{id}`   | Bearer      | one verified organization, or your own pending record |
| POST   | `/api/surplus`              | Bearer      | list surplus food from your restaurant  |
| GET    | `/api/surplus`              | Bearer      | live listings, soonest expiry first; optional `available_only` |
| GET    | `/api/surplus/reservations` | Bearer      | your organization's reservations, newest first |
| POST   | `/api/surplus/{id}/reserve` | Bearer      | reserve some or all of a listing (verified organization) |
| GET    | `/api/admin/users`         | Bearer (admin) | accounts, newest first; optional `role`, `limit` |
| GET    | `/api/admin/organizations` | Bearer (admin) | every organization, pending first, with contact and owner |
| PUT    | `/api/admin/organizations/{id}/verify` | Bearer (admin) | verify an organization so it may reserve |
| DELETE | `/api/admin/organizations/{id}/verify` | Bearer (admin) | remove verification; new reservations are blocked |
| PUT    | `/api/admin/users/{id}/role` | Bearer (admin) | grant or revoke a role; the last active administrator is protected |
| PUT    | `/api/admin/users/{id}/active` | Bearer (admin) | `{"is_active": false}` suspends, `true` reactivates; a suspended driver's uncollected work returns to the pool |
| GET    | `/api/admin/audit`         | Bearer (admin) | privileged changes, newest first; optional `action`, `subject_id`, `limit` |
| POST   | `/api/uploads`              | Bearer      | multipart `file=@photo.png` → `{url}`   |
| GET    | `/uploads/{filename}`       | –           | serves an uploaded image                |

The first SQLite database file (`iftr.db`) is created on startup in the
backend working directory. Delete it to reset local data.

### Creating the first administrator

Registration is deliberately not a route to a privileged role. `POST
/api/auth/register` accepts only the participant roles (`customer`, `driver`,
`restaurant_admin`, `organization_admin`) — each is an onboarding intent whose
authority comes from a restaurant, organization or driver record — and answers
`422` for `admin` or `support`. An administrator is seeded from the server's
shell, where operating the deployment is already possible:

```bash
cd backend
./run.sh create-admin you@example.com                     # prompts, twice
./run.sh create-admin ops@example.com --password-stdin < secret.txt
```

An address that already has an account is promoted in place and keeps its
password, so the command is safe to re-run and cannot lock anybody out. The
password is never echoed, logged, or passed as a command argument: it comes from
`getpass` or from stdin. Exit code `0` means done; `2` means it refused (a bad
address, a password under eight characters, or no terminal to prompt on).
Promotion takes effect immediately — the role is read from the database, not
from a token's old claim. The command also creates the tables it needs if the
deployment has never started (`users` and `audit_events`), so the first
administrator can be seeded before the API's first run. The grant is written to
the audit trail with `actor_kind=cli`, because no signed-in account made it.

### The audit trail

Privileged changes are written to `audit_events` in the same transaction as the
change itself: the promotion and the record of it commit together, so a failed
request cannot leave one without the other.

| Action | Written when |
| --- | --- |
| `user.role_changed` | registering a restaurant, signing up as a driver, registering an organization, an admin granting/revoking a role, or `create-admin` creating/promoting an administrator |
| `user.suspended` | an admin suspends an account |
| `user.reactivated` | an admin reactivates a suspended account |
| `delivery.reassigned` | suspending a driver returns an accepted order (`assigned → ready`) or volunteer run (`assigned → pending`) to the pool |
| `organization.verified` | an admin verifies an organization |
| `organization.unverified` | an admin removes an organization's verification |

Each row names the subject, the value before and after, and who acted: the
account's `user_id` plus the role it held *at the time* (`actor_kind=user`), or
`actor_kind=cli` with no actor id for the shell command. Only transitions are
history — verifying an already-verified organization, promoting an account to
the role it already holds, or suspending or reactivating an account that is
already in that state writes nothing. `GET /api/admin/audit` reads the
trail newest first, filterable by `action` and `subject_id`; it is admin-only and
stores ids rather than emails, so the result is safe to export.

Roles are granted and revoked with `PUT /api/admin/users/{id}/role`, which is
how a second administrator or a support account comes into being. The last
active administrator cannot be demoted — a deployment with nobody able to
administer it is not a state a request can create. An administrator may step
down once another active one remains. Revoking a participant role changes the
label, not the records: a former restaurant owner still owns their restaurant,
because those endpoints authorize by ownership rather than by this string.

Suspension is the stronger tool when access must stop but ownership must not
change. `PUT /api/admin/users/{id}/active` with `false` records
`user.suspended`; login and every request made with an already-issued token are
refused from then on, while the role, restaurant, organization and driver rows
stay exactly where they were. `true` records `user.reactivated` and the same
account can sign in again — no replacement account, no password reset, and an
old token starts working again. The last active administrator cannot be
suspended, and suspended administrators do not count toward the role guard:
either would leave nobody who can reactivate an account.

Suspending a driver also settles the work they were holding. An order they
accepted but have not collected goes back to `ready` and reappears on every
driver board; a claimed volunteer run goes back to `pending` and reappears on
the volunteer board. The release is a conditional write - it only matches while
the delivery is still the accepted job that was read - so a pickup or a new job
landing while the administrator is suspending makes the leftover check refuse
the request instead of overwriting a transition that arrived first. Each
release is written to the trail as `delivery.reassigned` against the delivery,
in the same transaction as the suspension, and the response carries
`released_deliveries` so the console can say what moved. A driver who has
already collected the food is refused with `409`: the delivery cannot be handed
to somebody else, and locking the carrier out would only make it less likely to
arrive. There is no separate handoff endpoint yet, so a driver in that state
must finish the delivery before the account can be suspended.

### The admin console

[`frontend/src/pages/AdminUsers.js`](frontend/src/pages/AdminUsers.js) is the
screen that drives these controls, at `/admin/users`. It is in the sidebar for
administrators; anybody else sees an explanation instead of the controls, and
the API refuses them regardless.

- **Users** lists every account, searchable by name or email and filterable by
  role. The role is a select on the row: choosing a different one calls
  `PUT /admin/users/{id}/role` and updates the row in place. Demoting yourself
  re-reads `/auth/me`, so the sidebar and this page agree before the next click.
  Each row also carries Suspend/Reactivate: suspension asks first because it
  locks the account out, reactivation is a single tap. The confirmation says
  that uncollected work goes back to the board, and the toast names how many
  deliveries moved when any did. The summary counts only active administrators,
  matching the server's guard.
- **Organizations** puts pending applications first, with the contact email,
  phone, address and owning account — what a verification decision actually
  needs. Verifying is one tap; removing verification asks first and says what
  stops and what does not.
- **Audit trail** is the same `/admin/audit` read, newest first, filterable by
  action or subject id. Each entry names the subject (by name where the console
  has it), the before → after values, the actor, the role that actor held at the
  time, and when it happened.

A `403` from any admin request re-reads `/auth/me`. If the role has been revoked,
the page becomes the refusal screen instead of toasting the error over controls
that no longer work; if the account is still an administrator, the toast reports
the underlying refusal.

Accounts are listed up to the server's 200-row default and the trail up to 100
rows; neither supports pagination yet, so a deployment past that needs a "load
more" or server-side search. A role change is not confirmed — the select is the
action — while unverification and suspension are, because they take access away.
Reactivation is not, because it gives access back.

### Who may call the API

The frontend is served from a different origin than the API, so the API is told
which browsers may call it ([`app/cors.py`](backend/app/cors.py)). Two settings,
read at startup:

| Name | What it is |
| --- | --- |
| `FRONTEND_ORIGINS` | exact origins, comma-separated — `https://shareplate.pages.dev`, or the ephemeral port the browser test serves itself on |
| `FRONTEND_ORIGIN_REGEX` | one pattern for origins that cannot be listed, which is what pull request previews are |

The two dev-server ports (`localhost:3000`, `localhost:5173`) always work.
Nothing is wildcarded: the API answers with credentials, and a wildcard would let
any site read a signed-in user's data.

Previews get a hostname per pull request — `pr-<number>.<project>.pages.dev` — so
they can only be admitted by pattern, and the pattern must name the project,
otherwise it admits every preview hosted on Pages:

```bash
FRONTEND_ORIGIN_REGEX='https://pr-\d+\.shareplate\.pages\.dev$'
```

[`tests/test_cors.py`](backend/tests/test_cors.py) checks both halves: that the
settings are read as described, and that the middleware actually refuses an
origin the pattern does not cover — including `…pages.dev.evil.example`, which a
pattern without the `$` would accept.

### Tests

```bash
cd backend
pytest                                  # the whole suite
pytest tests/test_uploads_gc.py -v      # one area
```

The suite in [`backend/tests/`](backend/tests/) covers auth, restaurants and
menus, the restaurant order queue — including which status moves an owner may
and may not make — organizations, surplus food and volunteer runs (listing,
reserving a listing between two organizations, claiming the run, walking it to
delivered or returning it before pickup, and counting the portions once), the
community support board (asking, answering, one vote per person, and only the
asker accepting an answer), the community impact feed (counts that follow real
rescues and delivered orders rather than demo totals), driver earnings (the
windows keyed to the delivery timestamp, volunteer runs counted separately), the
payments dev script (which key wins, and that `--check` prints no secret) and
payments (checkout amounts taken from the order, status polling, webhook replay
and signature verification, against a fake gateway, plus the diagnostics
endpoint telling a test key from a live one without ever including it), uploads,
the cleanup sweep and the create-admin command — including their flags and exit
codes — the audit trail (who changed a role, that a repeated verification writes
once), admin grants/revocations, suspension/reactivation and the last active
administrator guard, unverification's
effect on new versus accepted reservations, and the background scheduler. It is safe to
run against a working checkout: `tests/conftest.py` points the app at a
throwaway database, uploads directory and cleanup log before importing it, so
your `iftr.db` and `backend/uploads/` are never touched. `httpx` is needed for
`fastapi.testclient` and is listed with the dev tools in
[`backend/requirements.txt`](backend/requirements.txt).#### The frontend/backend route contract

[`tests/test_frontend_contract.py`](backend/tests/test_frontend_contract.py)
scans the pages for the API calls they make and resolves each one against the
routes the app actually serves, so a page built against an endpoint nobody has
written fails the suite by name instead of erroring in the browser. The calls
the UI makes ahead of their endpoints are listed in `KNOWN_MISSING` there — the
same inventory as "not yet implemented" below — and the test fails if a listed
entry has since been implemented, so that list has to shrink as slices land.

The scan finds the API base constants in the source rather than assuming one
(`lib/images.js` derives `API_BASE` from its own constant, so the upload field
would otherwise be invisible to it) and compares path parameters position by
position, so `/restaurants/{id}/orders` and `/restaurants/{id}` stay distinct.
It needs `frontend/src` to be present and skips without it.

It also fails when it meets a call it cannot read — a URL built into a variable,
or `fetch` — since an unread call is an unchecked one. It reads
`axios.<method>(`<url>`)`; extending it for another shape means teaching it the
method too.

#### The journeys, through the screens

Four browser modules drive the UI. They share one session-wide pair of
throwaway servers and one seed ([`tests/ui_world.py`](backend/tests/ui_world.py)),
so the CRA compile and database setup happen once; startup, shutdown and the
login form live in [`tests/ui_harness.py`](backend/tests/ui_harness.py).

[`tests/test_e2e_checkout.py`](backend/tests/test_e2e_checkout.py) signs in as a
customer, a cook and a courier and clicks the order through: pick a dish and
place the order, confirm / cook / mark ready, accept / collect / drive /
complete, and back to the tracker to see "Order delivered". The accounts,
restaurant and menu are made over the API first — registering a restaurant by
hand is a different test — but everything from the cart onwards is the UI.

[`tests/test_e2e_admin_console.py`](backend/tests/test_e2e_admin_console.py)
seeds the first administrator with the same CLI the deployment uses, then
changes a driver to Support from the user list, verifies a food bank and takes
the verification away in the confirmation dialog, and reads the three events in
the audit tab, newest first. It also checks the action and subject filters, so
the screen is exercised as a way to investigate one account rather than only as
a list. A second test tries to demote the only administrator: the console must
show the refusal, settle back on the role the server still holds, and leave no
audit row behind. A third promotes a second account, steps the original down,
and opens the console as the new administrator before restoring the original —
the guard must permit a handoff, not just refuse the last one. Before each admin
journey a reset puts the seeded roles, the pending application and the original
administrator back through the same API, so all eight can run in any order. One
stays signed in as a customer: the page must show the refusal, and that account's
token must be rejected by the admin reads and by a request to promote itself.
Another demotes the open administrator from another session and checks the next
request replaces the console with the refusal screen instead of a toast. The
sixth suspends a driver and reactivates them, checking both states in the row and
both audit entries. The last gives a driver an accepted order before the console
opens, suspends them, and checks the toast names the delivery that moved,the trail carries the reassignment against the order's own id, and the next driver's
board offers it. The last is about the deployment rather than an account: with a
live Stripe key and no signing secret the console must open with its loud banner
and both reasons, with a test key and no signing secret the banner must name the
webhook alone, and with a test key that can verify events the banner must be
gone and the tab must say so. Because the banner is the API's answer rendered,
that journey replaces the API process between assertions — same port, same
database, same signed-in page — and puts the seeded environment back before the
checkout module runs against the same server.

[`tests/test_e2e_surplus.py`](backend/tests/test_e2e_surplus.py) runs two
journeys. One volunteer works a claimed run from the driver screen: the card
shows both addresses, each button advances one stage, completing it removes the
card and says how many portions were received, and the organization's counter
and reservation status agree afterwards. Another abandons an uncollected run
through the confirmation dialog and checks the run is back on the board with the
reservation still `pending` and no counter moved.

[`tests/test_e2e_community.py`](backend/tests/test_e2e_community.py) asks a
question through the support dialog, has another account answer it over the
API, then upvotes (twice, to see the count stay at one) and accepts it as the
asker; the API afterwards agrees the question is resolved by that answer. A
second journey opens the impact and earnings screens as ordinary accounts and
asserts the feed answered - the "unavailable" notice is absent and the old
prototype's demo totals, invented trend and fake recent trips never render.

They are opt-in because they cost a minute or two and need node plus a browser,
neither of which the ordinary suite should require:

```bash
cd backend
python -m playwright install chromium     # once per machine
RUN_UI_E2E=1 pytest tests/test_e2e_checkout.py tests/test_e2e_admin_console.py tests/test_e2e_surplus.py tests/test_e2e_community.py
```

Without `RUN_UI_E2E=1` all four modules skip, so `pytest` stays as fast as it
was.

It is also the test that caught checkout reporting a placed order as a failure:
the payment hand-off 404'd while payments were unported, and the page used to
stay put on a "Failed to create order" toast with the order already in the
kitchen's queue. Now the order exists from the moment `POST /api/orders`
answers, and a payment step that cannot start (no key on the test server, a
provider outage) only means it is placed unpaid — the customer lands on the
tracker either way, and the message says nothing was charged.

#### Continuous integration

[`.github/workflows/tests.yml`](.github/workflows/tests.yml) runs three jobs on
`ubuntu-latest`:

- **Backend suite** — Python 3.14 and the same `pytest` a developer runs.
- **Frontend build** — `npm ci` then `npm run build`, so an import that resolves
  under the dev server's lazy compile but not in a production bundle fails the
  pull request instead of the deploy. The bundle is checked to exist and kept as
  the `frontend-build` artifact, which is the copy the deploy publishes.
- **Journeys through the UI** — needs the suite, installs Chromium and the
  frontend, and runs `tests/test_e2e_checkout.py`,
  `tests/test_e2e_admin_console.py`, `tests/test_e2e_surplus.py` and
  `tests/test_e2e_community.py` with `RUN_UI_E2E=1`.

Both frontend jobs install with `npm ci --legacy-peer-deps` because the lock has
`react-day-picker@8` asking for `date-fns` 2 or 3 while the app pins 4; plain
`npm ci` refuses that pair. `npm ci` also needs `frontend/package-lock.json` to
be committed. The build sets `CI=false` because CRA turns every warning into a
failed build and the ported pages still carry `react-hooks/exhaustive-deps`
warnings — this job is there to catch broken imports, not warning debt. It bakes
the API origin in: `main` gets `REACT_APP_BACKEND_URL`, everything else gets
`PREVIEW_BACKEND_URL`, so a preview's bundle talks to the preview API rather than
production's. An unset variable falls back to `http://localhost:8000` with a
warning — never to the other environment's API, because a preview that quietly
talked to production is how a review writes to real data. It builds without
source maps because that bundle gets published.

##### What is cached, and what cancels

Four choices in these files are deliberate rather than defaults, and each is
easy to delete without noticing what it held up:

- **The caches are keyed on the manifest, not on the tree.** `setup-python`
  caches pip against `backend/requirements.txt`, `setup-node` caches npm against
  `frontend/package-lock.json`. Editing source reuses the cache; editing either
  manifest is a miss, which is correct — that is the only change that can alter
  what has to be installed. Keying on the tree instead would miss on every
  commit and save nothing.
- **Tests cancel per ref** ([`tests.yml`](.github/workflows/tests.yml)).
  `group: tests-${{ github.ref }}` with
  `cancel-in-progress: true`: a second push to one branch makes the first run's
  verdict pointless, and only the last one describes the tip.
- **Deploys cancel per branch, except production**
  ([`deploy.yml`](.github/workflows/deploy.yml)). The group is the head branch
  and `cancel-in-progress` is true only when `Tests` was triggered by a pull
  request: a newer commit makes that PR's older preview pointless, but a
  production publish is never cut off halfway, which would leave the site on a
  bundle nobody chose.
- **Preview cleanup never cancels**, so a half-run cleanup cannot leave behind
  exactly what it exists to remove — the alias and its deployments. That is the
  `cancel-in-progress: false` in
  [`preview-cleanup.yml`](.github/workflows/preview-cleanup.yml).

The burn-in has no concurrency group at all, and does not need one: each run
names its own compose project and takes free host ports, so two runs cannot
collide on separate runners, and the weekly schedule must not cancel somebody's
manual run.

#### Deploy

[`deploy.yml`](.github/workflows/deploy.yml) publishes the frontend to
Cloudflare Pages, and only from a green run: it triggers on the `Tests`
workflow completing, downloads the `frontend-build` artifact that run uploaded,
and pushes it with `wrangler pages deploy`. Publishing the artifact rather than
rebuilding is the point — what goes live is the bundle the build job checked,
not a second one that could differ.

Where it goes depends on what ran:

| `Tests` ran because of | Published as | `--branch` |
| --- | --- | --- |
| a push to `main` | the production site | `main` |
| a pull request | a preview for that PR | `pr-<number>` |
| a push to any other branch | a preview for that branch | the branch, `/` → `-` |

So a pull request gets one stable preview URL that survives new commits, and the
production URL is only ever written by `main`. The link is posted on the pull
request itself — a single comment, rewritten in place on each push rather than
one per commit — as well as in the run's summary. That matters because the
deployment GitHub records belongs to the default branch's commit, not to the PR,
so without the comment a reviewer has nowhere to click.

Previews are built from the pull request's code and published with this
repository's credentials, so a fork's PR does get its output hosted — on a URL of
its own, never on the site's. GitHub runs this workflow from the default
branch's copy of it, so a PR cannot change what deploying does.

The job also writes `_redirects` into the bundle so client-side routes such as
`/orders/order_…` survive a refresh, and refuses an artifact with no
`index.html`.

It needs a Pages project that already exists — before publishing, the job asks
Cloudflare whether it is there and stops with an error naming it if not, rather
than leaving wrangler's 404 to be read as a credentials problem — plus these
repository settings:

| Name | Kind | What it is |
| --- | --- | --- |
| `CLOUDFLARE_API_TOKEN` | secret | API token with the *Cloudflare Pages: Edit* permission |
| `CLOUDFLARE_ACCOUNT_ID` | secret | the account the project lives in |
| `CLOUDFLARE_PAGES_PROJECT` | variable | the project to publish to (defaults to the repository name) |
| `REACT_APP_BACKEND_URL` | variable | the API the production site talks to |
| `PREVIEW_BACKEND_URL` | variable | the API the pull request previews talk to |

The two API variables are read by the build, not by the deploy: the origin is
baked into the bundle, so each run produces one artifact for one environment.
Point `PREVIEW_BACKEND_URL` at a deployment of the backend that the previews may
write to — its own database, not production's — and give that deployment a
`FRONTEND_ORIGIN_REGEX` covering the previews (see [Who may call the
API](#who-may-call-the-api)); without it the browser blocks every call with a
CORS error before the app can show anything.

The project's own production branch has to be `main` — that is the only branch
this workflow publishes as the real site. If the project was created against
another branch, a deploy with `--branch=main` would quietly become a preview and
the site would never update; change the production branch in Cloudflare instead
of editing the workflow. The job reads that field when it checks the project and
warns on a production deploy when it is not `main`, because that mistake is
otherwise invisible — the upload succeeds and the site simply never changes.

A deploy with neither API variable set publishes a bundle that talks to
`http://localhost:8000` — it loads, and every request fails. Both the build and
the deploy allow that but say so in an annotation, because a silent one is how a
site looks alive while being useless. Set the variable for the environment you
care about and re-run `Tests`.

The deploy also refuses a bundle whose JavaScript never mentions the expected
origin: a build that ran before the variable was set still says
`http://localhost:8000` and would otherwise publish happily. The string lives in
the entry chunk, not in `index.html` — the HTML links its scripts relatively —
so that is where it is looked for, and the error prints the origins the bundle
does contain. Seeing it means the artifact predates the variable: re-run
`Tests`, don't re-deploy.

##### Checklist for a first deploy

In this order. Steps 1–2 happen once; 3–4 are the pair that decides whether the
published site can talk to an API at all; 5 is the one people skip after
changing either of them.

1. **Cloudflare, once.** Create a Pages project (the repository name, or set
   `CLOUDFLARE_PAGES_PROJECT` to whatever you called it) and set its production
   branch to `main`.
2. **Credentials.** Settings → Secrets and variables → Actions, **Secrets**:
   `CLOUDFLARE_API_TOKEN` (a token with *Cloudflare Pages: Edit*) and
   `CLOUDFLARE_ACCOUNT_ID`. Environment-scoped instead? Put both on `production`
   *and* `preview` — the deploy job picks its environment by branch.
3. **The API origin.** The same page, **Variables** tab: `REACT_APP_BACKEND_URL`
   is the origin only — no trailing slash, no `/api`, because every call is
   `${origin}/api/…`. `PREVIEW_BACKEND_URL` is optional and only affects previews.
4. **The backend itself.** Something has to be serving `backend/` over HTTPS,
   with its own database and secrets, and its `FRONTEND_ORIGINS` has to include
   `https://<project>.pages.dev` (plus a regex for previews). No workflow here
   deploys it; without it the site loads and every call is blocked by CORS.
5. **Rebuild.** The origin is baked into the bundle at build time, so after
   setting or changing it, re-run `Tests` — the deploy republishes the artifact
   it is given and never rebuilds.

From then on a green `Tests` on `main` publishes the site and its run summary
carries the URL. A deploy with no Cloudflare secrets does not fail: it skips the
publish step with a notice saying which secret is missing, so the rest of the run
still reports its own result.

#### Preview cleanup

[`preview-cleanup.yml`](.github/workflows/preview-cleanup.yml) deletes a pull
request's preview deployments when it closes or merges. Cloudflare keeps them
otherwise, and every push adds another, so a long-lived pull request quietly
accumulates a pile of deployments behind one alias.

It runs on `pull_request_target` rather than `pull_request`: a pull request from
a fork receives no repository secrets, so the deploy token would be empty and the
preview would leak. Nothing from the pull request is checked out or run — it
lists deployments for the `preview` environment, keeps those whose branch is
exactly `pr-<number>`, and deletes each with `--force` (a preview carries the
alias being retired). A pull request with no previews is a no-op.

The sticky comment the deploy workflow left on the pull request stays put, so its
link stops resolving once the preview is gone. The comment is the record of what
was reviewed; a thread that quietly loses its evidence is worse than one dead
link.

### Uploaded images

Restaurant covers and menu item photos can either be a pasted URL or an
uploaded file. `POST /api/uploads` accepts a JPEG, PNG, GIF or WEBP up to
5 MB, stores it in `backend/uploads/` under a server-generated name, and
returns a backend-relative URL (`/uploads/<name>`).

Uploads are stored relative so records do not pin a hostname; the frontend
resolves them against `REACT_APP_BACKEND_URL` via `src/lib/images.js`.
`backend/uploads/` is gitignored — it holds local runtime data.

The type is decided by sniffing the file's leading bytes, not by the
filename or the declared content-type, so a renamed non-image is rejected.

## Frontend

```bash
cd frontend
npm install --legacy-peer-deps     # required: react-day-picker wants date-fns v2/3
npm start                          # http://localhost:3000
```

`.env` points the UI at the backend:

```
REACT_APP_BACKEND_URL=http://127.0.0.1:8000
```

### Port notes from the Emergent app

- The UI speaks in friendly roles (`restaurant`, `organization`); the backend
  uses canonical values (`restaurant_admin`, `organization_admin`). The mapping
  lives in `src/contexts/AuthContext.js`.
- Google OAuth was brokered by Emergent and is not wired up yet; the button
  fails softly.
- The Emergent visual-edits / health-check dev-server plugins are disabled in
  `craco.config.js` (they assumed Emergent's host).
- `ajv@^8` was added as a devDependency because npm (unlike the yarn install
  Emergent used) otherwise hoists `ajv@6` and breaks `schema-utils@4`.

### Reclaiming space from old uploads

Replacing a photo leaves the old file on disk: nothing points at it any more,
but nothing removes it either. Sweep those orphans whenever you like:

```bash
cd backend
./run.sh cleanup-uploads            # dry run — reports, deletes nothing
./run.sh cleanup-uploads --delete   # removes the unreferenced files
```

The sweep searches every text/JSON column of every mapped table for a
`/uploads/<name>` value, so a photo kept only by a menu item is kept, and a
table added later is covered automatically. Two guards: a file modified in the
last hour is never touched (the UI uploads as soon as you pick a file, but saves
the record later), and it refuses to delete anything when no table holds a row,
so a wrong `DATABASE_URL` cannot empty the folder. Override with
`--min-age-minutes 0` or `--force`.

Every run - dry runs and refusals included - is appended to
`backend/logs/uploads_cleanup.log`, so what was reclaimed and how much space it
freed is readable afterwards instead of scrolling off the terminal:

```
2026-10-12T01:52:07+00:00  delete: 2 file(s) deleted, 195 KB reclaimed | on disk 4 (328 KB), referenced 2, too new 0, unmanaged 0
  deleted: 0e7fc151419641da8be4a2b77de89ca5.png (70 B)
```

Point it elsewhere with `--log-file PATH`, or skip the entry with `--no-log`.
`backend/logs/` is gitignored. Logic lives in
[`backend/app/uploads_gc.py`](backend/app/uploads_gc.py), CLI in
[`backend/cleanup_uploads.py`](backend/cleanup_uploads.py).

### Automatic sweep

The backend also runs that sweep on its own - see
[`backend/app/uploads_gc_scheduler.py`](backend/app/uploads_gc_scheduler.py):
started with the app, once at boot and then every `UPLOADS_GC_INTERVAL_MINUTES`
(default 60). Set it to `0` to turn the background sweep off.

It uses the same guards as the command, so a photo uploaded moments before a
restart is safe. Idle intervals are left out of the log to keep it
event-driven; failures and refusals are reported at ERROR level and never stop
the schedule. Start uvicorn with a single worker (the default, and what
`run.sh` does) so two processes do not sweep at the same time.

### Images in the UI

`src/components/ImageUploadField.js` is the shared picker used by the
restaurant form and the menu item dialog. It offers two modes — upload a file
(click or drag onto the dropzone) or paste a URL — and hands the parent a
plain string for the `image_url` field either way.

Not yet implemented: contribution scores and the Google sign-in session
exchange (`POST /auth/session`) that Emergent used to broker. Payments are in
(see [Payments](#payments-stripe-checkout)), but they are optional: with no
Stripe key the app still places orders and says so.
Pages that need them error until their endpoints land — the exact list of calls
they make is held by `KNOWN_MISSING` in
[`tests/test_frontend_contract.py`](backend/tests/test_frontend_contract.py),
which fails whenever it drifts from what the frontend asks for.

### Orders

The whole lifecycle is in, split between the two screens that work it
(`app/api/orders.py` and `app/api/drivers.py`, rules in `app/order_flow.py`):

```
pending --restaurant--> confirmed --> preparing --> ready --driver--> assigned
  |                        |                                            |
  +--- cancelled <---------+                          picked_up -> in_transit -> delivered
```

One endpoint serves both screens (`PUT /api/orders/{id}/status?status=`), and
who is acting is resolved from the database — the owner of the order's
restaurant, or the driver the order is assigned to — never from the request. The
edge and the right to take it are checked separately, so the two refusals mean
different things: `409` when the move does not exist at all (a kitchen cannot
mark food delivered), `403` when it exists but belongs to the other party (a
kitchen cannot take over a driver's job).

Claiming is the one transition with no role: `ready -> assigned` is taken by
`POST /api/drivers/accept-order/{id}` alone, because it also has to stamp the
driver onto the order. It is a single conditional write, so two drivers tapping
at the same moment resolve to one winner and one "Order already taken" rather
than an overwrite.

A job **on offer** carries the shape of the work but not the customer: what is
in the bag, the fee and the tip, and no name, address or door code. A job **in
hand** adds both ends of the trip, because by then the driver has to go. The
pickup address is read from the restaurant rather than copied onto the order, so
a restaurant that moves is still found.

Going offline empties the board (otherwise the toggle would mean nothing), and
does not abandon a job already accepted.

`assigned` is the one status with no step on the customer's tracker: the food is
still on the kitchen counter, which is where the tracker already sits, so the
page reads the job as `ready` and says the driver is on the way to collect it.
Without that the stepper fell back to "Order Placed" the moment a driver took
the order - the page regressing at the first sign of progress.

When a suspended driver's accepted order comes back to the pool, the tracker
says so. `GET /api/orders/{id}` and the customer's order list carry
`reassignments`, one timestamp per return, read from the same
`delivery.reassigned` audit rows the admin trail uses rather than a second copy
on the order. The customer is told the courier changed, and once another driver
claims it, whose delivery it now is; the administrator who moved it and the
fact that the previous courier was suspended stay in the admin trail. Nothing
is projected that would turn an operational decision into a judgment the
customer can read, and the notice carries no administrator id or suspension
wording.

### Checkout

`POST /api/orders` is where orders come from. The customer chooses what to
order; the restaurant's stored menu decides what it costs. Prices, names and the
`is_drink` / `is_sealed` flags on every line are copied from the menu, so a
doctored request can change what is ordered but not what it costs, and an item
the menu no longer lists (or has switched off) is refused rather than priced
from the request. The rules live in
[`backend/app/pricing.py`](backend/app/pricing.py): a flat 2.99 fee below a 30
subtotal, multiplied by the speed the customer chose (priority ×1.5, economy
×0.5). No tax is charged, because nothing charges tax yet.

One number to be careful with: `total_amount` is the whole bill - subtotal plus
delivery fee plus tip. The Emergent API left the fee out of its total and the
ported order list and tracking pages added it back, so an $8.99 order read as
$11.98 on both while checkout had charged $8.99. The screens now print
`subtotal`, `delivery_fee`, `tip_amount` and `total_amount` as stored, and
`tests/test_frontend_contract.py` fails if a page ever recombines the last two.

The customer's choices are stored in two satellite tables rather than columns on
`orders` — `order_locations` (the encrypted dropoff, see the driver section) and
`order_delivery_details` (the instruction and the speed). That is not a
preference: there is no migration tool here, so `create_all` adds new tables to a
database that already exists and never new columns to the tables in it.

**Scheduling** is deliberately not honoured: it is refused with an explanation
instead of accepted and ignored, because cooking a "7pm" order now would tell
the customer something untrue.

**Payment** is a hosted Stripe Checkout session opened after the order exists
(see below). The order and the payment are separate records on purpose: the
order is what the kitchen works, the payment is what the provider confirms. An
order can be pending or failed and still be visible, which is why the kitchen
queue labels it rather than hiding it.

A customer may cancel their own order while it is still `pending` — the third
actor in `app/order_flow.py`, with that one edge. Once the kitchen starts, the
decision is the restaurant's; after pickup it belongs to support.

Who may read an order is decided per order, not per role: the customer who
placed it, the owner of the restaurant making it, or the driver carrying it.
Neither "a restaurant account" nor "a driver" is enough on its own.

### Payments (Stripe Checkout)

A customer pays on Stripe's hosted page; the app never sees or stores a card.
The endpoints are in [`app/api/payments.py`](backend/app/api/payments.py), the
SDK is isolated in [`app/payments.py`](backend/app/payments.py), and the payment
state lives in the `order_payments` satellite table
([`app/models/payment_orm.py`](backend/app/models/payment_orm.py)) for the same
no-migrations reason as the other satellites. Every webhook attempt, including
the ones refused for their signature, is written to
`payment_webhook_deliveries`
([`app/models/webhook_orm.py`](backend/app/models/webhook_orm.py)); that table is
what `GET /api/payments/diagnostics` reads back.

| Variable | What it is |
| --- | --- |
| `STRIPE_SECRET_KEY` | `sk_test_…` or `sk_live_…`. Absent means the app takes no money: checkout answers `503` and orders stay payable later. |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` from the webhook endpoint. Without it the webhook refuses every event; the success page's polling still works. |
| `FRONTEND_ORIGINS` | Where Checkout sends the customer back to. The `origin_url` the browser sends is checked against this same CORS list (plus `FRONTEND_ORIGIN_REGEX`), so a caller cannot redirect the payer somewhere else. |

What happens, in order:

1. `POST /api/orders` creates the order, unpaid. Nothing has been charged yet.
2. `POST /api/payments/checkout` checks the caller owns the order, takes the
   amount from the stored bill (never from the request), and creates a Stripe
   Checkout Session with the food, delivery and tip as separate lines. The
   response is the session's hosted URL; the browser redirects there.
3. Checkout returns to `/payment/success?session_id=…`, and that page polls
   `GET /api/payments/status/{session_id}`. The endpoint asks Stripe, then marks
   the order paid only if the session names   the order **and** its amount equals
   the order's total. A hand-edited URL cannot settle anything, and neither can
   a session for a different amount.
4. `POST /api/payments/webhook` is the same confirmation without the browser:
   `checkout.session.completed`, `async_payment_succeeded`,
   `async_payment_failed` and `expired` are handled, verified against
   `STRIPE_WEBHOOK_SECRET` with the raw body. It is idempotent, so Stripe's
   retries and the success page can both report the same payment.

A session that is still open is handed back instead of replaced, so a
double-click or a refresh cannot open two payment pages. Once a session expires
or fails, the next attempt gets a new one (and a new idempotency key). The
customer can retry from the **Pay** button on their orders page.

Local testing is one terminal, with a test-mode key in `backend/.env`:

```bash
cd backend
./dev_payments.sh        # API + `stripe listen`; Ctrl+C stops both
```

That script reads `backend/.env` then `backend/.env.local` (neither is
committed, and a variable already in your environment wins over both). It
starts the listener **first** and takes the signing secret that listener prints
for itself, handing it to the API — a Dashboard endpoint's `whsec_...` cannot
verify events the CLI signs, so nothing has to be copied and the API does not
need restarting once the listener is up. `--check` prints what it would do
without starting anything or showing a key, `--api-only` runs just the API
(using `STRIPE_WEBHOOK_SECRET` if you have one), `--env-file PATH` reads another
file, and logs land in `backend/logs/dev_payments/`. If the port is taken — a
second checkout, an earlier run — it moves up to the next free one and points
the listener at that port, so the two never disagree. When no key or no Stripe
CLI is present it says so and runs the API alone, because checkout's `503` is a
supported state rather than a crash. A live key (`sk_live_...`, `rk_live_...`)
is refused with exit `2` before anything starts — this server would charge real
cards — and `--allow-live` is the explicit way to say you mean it; `--check` still
reports the setup and the refusal without starting anything.

The manual route is still two terminals:

```bash
# Terminal 1: the API
cd backend && ./run.sh

# Terminal 2: forward Stripe's events to it
stripe listen --forward-to localhost:8000/api/payments/webhook
# copy the printed whsec_... into STRIPE_WEBHOOK_SECRET and restart the API
```

Use card `4242 4242 4242 4242`, any future expiry and any CVC. Stripe's CLI
needs the webhook secret; without it the success page's polling still confirms
the payment, and only tab-closed payments depend on the webhook. Never put a
live key in the repository or in a test environment.

#### Diagnosing a payment setup

`GET /api/payments/diagnostics` (administrators only) answers the four questions
that are otherwise indistinguishable from the outside:

```bash
curl -s localhost:8000/api/payments/diagnostics -H "Authorization: Bearer <admin token>"
```

- **Is a key configured at all?** `configured` / `checkout_available`, and
  `key_mode` is `test`, `live`, `unset` or `unrecognised`.
- **Will it charge a real card?** `live_mode` is true only for an `sk_live_` or
  `rk_live_` key, and `warnings` says so in a sentence.
- **Can events be verified?** `webhook_secret_configured`, `webhook_path` and the
  `handled_events` list. With no signing secret the webhook refuses everything
  with `503`, which looks exactly like a listener that is not running.
- **Did Stripe ever reach us?** `webhook.last_received_at`,
  `last_event_type`, `last_outcome` (`settled`, `ignored`, `unmatched`,
  `unhandled`, `rejected`, `unconfigured`), `last_rejected_at`, and counts for
  the last 24 hours.

It reads the environment and the delivery table and never calls Stripe, so it
still answers when the thing it is describing is broken. No key, and no part of
one, appears in the response — only the prefix Stripe itself treats as public
(`sk_` vs `rk_`, `test` vs `live`). A stream of `rejected` deliveries with no
`last_verified_at` beside it is the signature of a `whsec_...` copied from the
Dashboard that cannot verify what `stripe listen` signs; no deliveries at all
means the listener is not forwarding, or points at another port (the dev script
moves both together when 8000 is taken). Delivery rows are capped at the newest
500, so the table cannot grow without bound under Stripe's retries.

What is **not** implemented: refunds and driver/restaurant payouts, tipping
after a payment (the bill cannot change under an open Checkout page, and there
is no second charge to put a later tip on), and paying for a scheduled order
(scheduling itself is refused). A paid order that is later cancelled is **not**
refunded automatically — no code path moves money back yet, so that is a
provider-dashboard or support action. An order that is never paid stays in the
kitchen queue labelled `Payment pending` — the restaurant can see the state and
nothing in the flow pretends the money arrived. Bitcoin and Monero are a
separate flow with no processor in the middle; the next section is the honest
version of it.

### Crypto payments (Bitcoin and Monero)

The card flow is a redirect and a webhook. Crypto is neither: there is nobody to
call us back, so a payment is a **quote**, an **address**, and a **watcher**
([`app/crypto.py`](backend/app/crypto.py) for the arithmetic,
[`app/crypto_flow.py`](backend/app/crypto_flow.py) for the state machine,
[`app/api/crypto.py`](backend/app/api/crypto.py) for the routes, and
[`app/crypto_watcher.py`](backend/app/crypto_watcher.py) for the timer).

1. `POST /api/payments/crypto/invoice` takes the amount from the stored order,
   prices it at a recorded USD rate, and asks the wallet for a **fresh address
   for that one invoice**. Both the amount and the rate become part of the
   invoice, so a later question about the price has an answer.
2. The page at `/payment/crypto/:order_id` shows the address, the amount and a
   QR of the wallet URI, counts the quote down, and polls
   `GET /api/payments/crypto/status/{order_id}`.
3. The background watcher asks the wallet on a timer, which is what catches a
   payment made after the customer closed the tab. Either path settles the sale
   by writing the **same `order_payments` row a card writes**, so the kitchen
   queue, the driver board and the revenue totals keep working unchanged.

Money is counted in integer atomic units (satoshi, piconero) from the first line
to the last; a float never touches an amount. Quotes round **up**, because an
invoice one unit short is an invoice that can never be settled by paying it.

Two ways to be paid, two wallet setups. Neither wallet is asked for a key that
can spend:

* **Bitcoin Core, watch-only.** Import the receiving descriptor (or xpub) into a
  wallet with `disable_private_keys=true`, then give the API that wallet's RPC
  URL and name. `getnewaddress` derives per-invoice addresses this server can
  watch and cannot spend from.
* **`monero-wallet-rpc`.** Run it on the same host as the API, bound to
  `127.0.0.1`, with `--rpc-login`. It holds the view key and usually the spend
  key, so it is the one process here whose compromise costs money: keep it off
  the network, and treat its login as a spending credential rather than a
  setting. One subaddress per invoice, filtered by address when read back.

| Variable | What it is |
| --- | --- |
| `BITCOIN_RPC_URL` | e.g. `http://127.0.0.1:8332`. Unset means no Bitcoin invoices. |
| `BITCOIN_RPC_USER`, `BITCOIN_RPC_PASSWORD` | The node's RPC login. Never the wallet's. |
| `BITCOIN_WALLET` | The watch-only wallet name, so the call lands in `/wallet/<name>` instead of bitcoind's default. |
| `MONERO_WALLET_RPC_URL` | e.g. `http://127.0.0.1:18083/json_rpc`. Unset means no Monero invoices. |
| `MONERO_WALLET_RPC_USER`, `MONERO_WALLET_RPC_PASSWORD` | The `--rpc-login` pair. |
| `CRYPTO_RATE_URL` | Where the USD price comes from. Defaults to CoinGecko's `simple/price`; point it at your own feed or a stub. |
| `CRYPTO_QUOTE_MINUTES` | How long a quote is offered (default `15`). |
| `CRYPTO_GRACE_HOURS` | How long an expired invoice keeps being watched (default `24`), because late money is still money. |
| `CRYPTO_MIN_CHARGE_CENTS` | Below this, no crypto invoice is offered (default `100`): the network fee would be most of the bill. |
| `CRYPTO_BTC_CONFIRMATIONS`, `CRYPTO_XMR_CONFIRMATIONS` | Depth before an order counts as paid (defaults `1` and `2`). |
| `CRYPTO_WATCH_INTERVAL_SECONDS` | Seconds between watcher sweeps (default `30`); `0` turns the watcher off. |

With no wallet configured the feature is simply off: `GET /api/payments/methods`
says so, the orders page does not offer the button, and the invoice route answers
`503` with a sentence. That is the same supported state as a missing Stripe key —
the order exists and stays payable.

The customer-facing rules are deliberately conservative: one open invoice per
order (asking again for the same coin hands back the same address, a second coin
is refused), an open crypto invoice blocks a card checkout, an expired quote
frees the card route without stopping the watch, and a paid order cannot be
invoiced again. A quote whose rate feed is down is refused rather than guessed:
crypto has no chargeback, so a wrong charge is permanent.

For development, `tests/test_crypto_wallets.py` pins the JSON-RPC calls against
a stub server, and `tests/test_crypto.py` runs the whole flow against a wallet
that has a memory and a fixed rate:

```bash
cd backend && python -m pytest tests/test_crypto.py tests/test_crypto_wallets.py -q
```

What this is **not**, said plainly:

* **Not a substitute for a node.** The adapters are pinned against a stub, not
  against a synced bitcoind or monero-wallet-rpc. A real node can refuse a
  method, answer an error, or be a wallet the RPC does not know; the honest
  evidence here is the request shape, and the README of a payment feature should
  say so before somebody trusts it with money.
* **No refunds, no payouts, no fee handling.** Nothing in this codebase moves
  coin back out. A cancelled order paid in crypto is a support action in the
  wallet, exactly like a card refund is today. Network fees are paid by the
  customer and are not quoted.
* **The rate is one source, cached for a minute.** A manipulated or stale feed
  means a bad quote; the short window limits how much of the price can move
  before the quote expires, and nothing more.
* **Confirmations are a compromise.** One Bitcoin block and two Monero blocks
  are what makes a food order payable in minutes. That is less finality than
exchange deposit policies ask for, and the README would rather say so than
imply the risk is gone.
* **One watcher per process.** Run uvicorn with one worker. A second watcher
  would not double-settle anything (settlement is guarded) but would double the
  wallet traffic.
* **No privacy story beyond the address.** A fresh address per invoice stops
  other customers from reading your history, but the server still knows which
  order an address belongs to, and the order still carries a delivery address.
  Monero hides the amount and the parties on-chain; it does not hide them from
  this application.
* **Taxes and money transmission are yours to check.** Selling food for coin is
  a taxable event in most places and may be a regulated activity; nothing here
  computes a gain or files anything.

#### The burn-in, against real nodes

The stub tests pin this app's side of the conversation. They cannot tell you
that bitcoind accepts the watch-only descriptor, that `monerod --regtest` reports
depth the adapter reads, or that a payment settles with nobody looking at the
page. `tests/test_crypto_burnin.py` can, because it runs against containers:

```bash
cd backend
RUN_CRYPTO_BURNIN=1 python -m pytest tests/test_crypto_burnin.py -v
```

[`burnin/compose.yaml`](backend/burnin/compose.yaml) starts bitcoind on regtest,
monerod on regtest (offline, `--fixed-difficulty=1`, so blocks are mined on
demand), and **two** wallet-RPC daemons: the merchant's, which the app talks to,
and a funder's, which stands in for the customer's wallet. One daemon cannot
hold both: `monero-wallet-rpc` keeps one wallet open, and the app must keep
its own open while the test spends from another.

The harness creates the wallets over RPC. For Bitcoin that means a miner with
real keys and a blank, keyless wallet given the miner's **public** ranged
descriptor - the same setup this README tells you to run - and it checks
`getwalletinfo` says `private_keys_enabled: false`, so the claim is verified
rather than assumed. It then funds the Monero funder with regtest blocks, starts
the real API with those endpoints in its environment (and therefore the real
watcher), and pays two invoices.

That last detail is the point: the burn-in waits on `GET /api/orders/{id}` to
say paid, never on the payment-status endpoint, so a settled order is the
watcher's doing and not the page's. It also pays half an invoice and expects
`partial` and an unpaid order, because "we can see it" and "it is paid" are the
two answers a bug here would conflate.

It takes a few minutes - three images (one of them used twice), 101 Bitcoin
blocks, 70 Monero blocks, all regtest - removes its containers and volumes
afterwards (`docker compose down -v`), and writes compose, container and API
logs to `backend/logs/burnin/`
(git-ignored). Images are pinned in the compose file and overridable with
`BURNIN_BTC_IMAGE`, `BURNIN_MONEROD_IMAGE` and `BURNIN_XMR_WALLET_IMAGE`.

Where Docker is absent the burn-in skips with a sentence, and
[`tests/test_burnin_harness.py`](backend/tests/test_burnin_harness.py) still
runs: it drives the harness's provisioning and payment helpers against a
scripted node and asserts the payloads (the active descriptor and its range, the
keyless wallet, the exact invoice amount, piconero to the subaddress), which is
what catches a typo before the slow run does. CI runs the whole thing on demand
and weekly ([`.github/workflows/burnin.yml`](.github/workflows/burnin.yml)).

What the burn-in still does not prove: mainnet behaviour. Regtest has no
meaningful reorgs and no fee market, so the confirmation policy and the late
money window remain reasoned choices rather than measured ones.

### Surplus food and volunteer runs

A listing becomes a rescue in three steps, each with its own record
(`app/api/surplus.py`, `app/api/drivers.py`):

```
restaurant lists surplus --> organization reserves portions --> volunteer delivers
   surplus_food                surplus_deliveries (pending)        (assigned)
```

The reservation is the delivery row, not a counter on the listing. One listing
can be split between two organizations, and each organization's received page
must show the number of portions *it* booked and the state of *its* run; a
single `reserved_by_org_id` cannot say that once two organizations are involved.
So a reservation decrements the shelf and writes a `surplus_deliveries` row with
the organization's own quantity, pickup and dropoff. `GET /api/surplus` answers
"what is left"; `GET /api/surplus/reservations` answers "what did I book".

Stock is taken with one conditional `UPDATE ... WHERE quantity >= requested AND
is_available AND expiry_time > now`. Two organizations tapping "reserve the last
three" at the same moment resolve to one winner and one "Only N portion(s)
left", never to a negative shelf; the listing closes itself (`is_available`
flips to false, `reserved_by_org_id` is stamped) only when the last portion goes.

Listing is restricted to a registered restaurant, and the pickup point is copied
from that restaurant rather than taken from the request, so a listing cannot
point a volunteer at an address the restaurant does not have. Browsing returns
the city but no address or coordinates; a driver gets both addresses only after
taking the run, the same rule order offers follow. The run is quoted on the
volunteer's own vehicle, so a job that is a short drive is not advertised as a
short walk.

Reserving requires a verified organization, and verification is an admin call
(`PUT /api/admin/organizations/{id}/verify`). The first administrator comes from
[`./run.sh create-admin`](#creating-the-first-administrator), never from
registration. A freshly registered organization
browses and sees "Verification Pending" until then. An administrator can also
unverify it (`DELETE` on the same path): new reservations are refused from that
moment, while runs already accepted keep going so food in hand is not stranded.
A claimed run no longer stops at `assigned`. `GET /api/drivers/active-surplus`
is the driver's own list of runs in hand (the public board only offers runs
nobody has taken), and `PUT /api/drivers/surplus-deliveries/{id}/status` walks
one forward: `picked_up` → `in_transit` → `delivered`. Only the volunteer
carrying it may advance it, and only one step at a time; the write is
conditional on the status that was read, so a retried "Complete" is refused
instead of delivering the same food twice.

Before pickup, the carrying volunteer can hand the run back with
`POST /api/drivers/surplus-deliveries/{id}/abandon`: it returns to `pending`,
clears the assignment and reappears on every volunteer board. The write is
conditional on the run still being the `assigned` row that was read, so a tap
that races a pickup cannot reopen a run whose food is already in hand. After
pickup the request is refused with `409`, because offering the food to somebody
else would send them to a counter that no longer has it.

`delivered` is the moment the rescue becomes a receipt. The same transaction
adds the run's portions to the organization's `total_received` and the
restaurant's `total_meals_donated`. Counting on `assigned` would include food
that never arrived; counting in a second request would leave a delivered run
that no counter knows about. The organization's reservations page shows the run
as `delivered`, the driver's active list drops it, and the driver screen has the
three step buttons plus the abandon action while the food is still at the
restaurant.

### Community support

`app/api/support.py` serves the board both community screens read:
`Support.js` as questions and answers, and `DriverRouting.js` as route tips,
which is why the category vocabulary includes `routing` alongside general,
delivery, payment, restaurant and technical. Any signed-in account may ask or
answer; an unknown category is a `422` rather than a question filed under
"general", because a filter that guesses is a filter that lies.

A vote is a row in `support_answer_votes`, keyed by (answer, person), not a bare
counter: the prototype's `$inc` let one account vote the same answer up as often
as it liked. The counter on the answer follows the row, so a retried tap answers
`200` with the count it already had. Names and roles are snapshotted on the post,
so the board still credits whoever wrote it after an account is renamed.

Only the asker may accept an answer (`403` for everybody else), and accepting is
what makes the question `is_resolved` true. Accepting a different answer moves
the mark and clears the old one in the same transaction — a question carries one
accepted answer, not a pile of them. The accepted answer sorts first, then by
upvotes, then oldest; the list shows the newest 50 questions with up to 10
answers each. `GET /api/support/questions?category=routing&resolved=false` is
how the tip screen asks for what is still open, and the page offers Accept on
answers to your own question.

### Community impact

`GET /api/impact/stats` feeds [`CommunityImpact.js`](frontend/src/pages/CommunityImpact.js)
and is open to every signed-in account, because counts of food moved are
community evidence rather than moderation data. The administrator dashboard
reads `GET /admin/stats` from the same `collect_stats` function and adds
`total_revenue`, which sums the orders whose payment row says `paid` — money
the provider confirmed. The dashboard's money card reads that, and the impact
page keeps `delivered_value` — what delivered orders were worth, whether or not
anyone paid — because the two answer different questions.

The numbers are deliberately not interchangeable: `meals_delivered` sums item
quantities on `delivered` orders; `meals_donated` is the organizations' stored
`total_received`, i.e. portions handed over; `surplus_saved` counts every
reserved portion however far its run has got; `organizations_helped` only
counts organizations that have received at least one portion. The screen used
to fall back to invented totals (12,847 meals and so on) whenever the call
failed — including for every non-administrator, since it asked an admin route
without a token. It now shows zeros and says the figures are unavailable,
because a demo number on the impact page reads as a real achievement.

### Driver earnings

`GET /api/drivers/earnings` backs [`DriverEarnings.js`](frontend/src/pages/DriverEarnings.js).
A completed trip is worth its delivery fee plus its tip — the price the
customer agreed to; no commission exists to subtract and no payout has settled.
Totals cover the driver's lifetime and three rolling windows (since UTC
midnight, the last 7 days, the last 30), keyed to `delivered_at`; a delivered
order with no timestamp counts only in the lifetime total. Recent trips are the
five newest with a delivery timestamp. Volunteer surplus runs are counted as
`surplus_runs` and never as paid deliveries, since they pay nothing.

There is no rating in the response: reviews are not merged, and the screen used
to print a hard-coded 5.0 plus demo trips and a "+12%" trend. Those are gone;
an empty list says there are no completed trips yet and the breakdown is the
real fee/tip split for the selected window.

### Logging out

`POST /api/auth/logout` exists so the sidebar's button has something to call;
it answers `200` with or without a token, because an expired token must not turn
logging out into an error. There is no server-side session to end — the JWT stays
valid until it expires, and the browser clearing its copy is what logs that
device out. Revoking a leaked token needs a denylist or short-lived tokens with
refresh, neither of which exists yet.

