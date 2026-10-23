"""
Paying in Bitcoin or Monero, through the routes the payment page calls.

No test reaches a node, a wallet or an exchange. `get_wallets` is replaced with
wallets that keep a memory of addresses and readings, and `get_rate_feed` with a
fixed price, which is what lets these tests assert this app's decisions: what is
quoted, when an invoice is refused, when an order becomes paid, and what happens
to money that arrives late.

The one thing the fakes cannot prove is that a real bitcoind or
monero-wallet-rpc answers these request shapes. That is what
tests/test_crypto_wallets.py pins, against a stub JSON-RPC server.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.crypto_watcher as watcher_module
from app.api.crypto import get_rate_feed, get_wallets
from app.api.payments import get_gateway
from app.crypto import (
    ASSET_BTC,
    ASSET_XMR,
    CryptoWalletError,
    CryptoWallets,
    RateUnavailable,
    WalletReading,
)
from app.main import app
from app.payments import CheckoutSession

# Two pizzas at 12.50, a 2.99 delivery fee and a 3.00 tip.
TOTAL_CENTS = 3099

# $60,000 a coin and $150 a coin. Chosen so the arithmetic is exact where it
# should be and fractional where the rounding-up test needs it.
BTC_RATE_CENTS = 6_000_000
XMR_RATE_CENTS = 15_000


class FakeWallet:
    """A wallet with a memory: addresses it issued, and what arrived at them."""

    def __init__(self, asset_code: str):
        self.asset_code = asset_code
        self.addresses = []
        self.labels = []
        self.readings = {}
        self.error = None
        self.asked = []

    async def new_address(self, label: str) -> str:
        if self.error is not None:
            raise self.error
        self.labels.append(label)
        address = f"fake-{self.asset_code}-{len(self.addresses) + 1}"
        self.addresses.append(address)
        return address

    async def received(self, address: str, *, confirmations: int) -> WalletReading:
        if self.error is not None:
            raise self.error
        self.asked.append((address, confirmations))
        return self.readings.get(address, WalletReading())

    def pay(self, address: str, amount_atomic: int, *, confirmations: int = 1, txid="tx-1"):
        """Money arrived. `confirmations` is how deep it is right now."""
        self.readings[address] = WalletReading(
            received_atomic=amount_atomic,
            # Anything at the required depth is settled; the invoice records the
            # depth it asked for, so a one-confirmation payment settles a policy
            # of one and does not settle a policy of two.
            confirmed_atomic=(
                amount_atomic if confirmations >= 1 else 0
            ),
            confirmations=confirmations,
            txid=txid,
        )


class FakeFeed:
    def __init__(self, rates=None, error=None):
        self.rates = {
            ASSET_BTC: BTC_RATE_CENTS,
            ASSET_XMR: XMR_RATE_CENTS,
        }
        if rates:
            self.rates.update(rates)
        self.error = error
        self.asked = []

    async def cents(self, asset) -> int:
        if self.error is not None:
            raise self.error
        self.asked.append(asset.code)
        return self.rates[asset.code]


class RecordingGateway:
    """A Stripe stand-in that answers a checkout and refuses to be asked more."""

    def __init__(self):
        self.created = 0
        self.retrieved = 0

    async def create_checkout(self, **kwargs) -> CheckoutSession:
        self.created += 1
        # Unique per call, because the database outlives this fixture: a session
        # id reused by a later test would collide with the row it wrote first.
        token = uuid.uuid4().hex[:12]
        return CheckoutSession(
            session_id=f"cs_test_crypto_guard_{token}",
            url=f"https://checkout.stripe.test/{token}",
            amount_cents=kwargs["amount_cents"],
            currency=kwargs["currency"],
        )

    async def retrieve(self, session_id: str):
        self.retrieved += 1
        raise AssertionError("a crypto session must never be asked of Stripe")

    def parse_webhook(self, payload: bytes, signature: str):
        raise AssertionError("no webhook is involved in this test")


@pytest.fixture
def wallets(client):
    """Both assets configured, with fake wallets, for one test."""
    btc, xmr = FakeWallet(ASSET_BTC), FakeWallet(ASSET_XMR)
    feed = FakeFeed()

    app.dependency_overrides[get_wallets] = lambda: CryptoWallets(
        {ASSET_BTC: btc, ASSET_XMR: xmr}
    )
    app.dependency_overrides[get_rate_feed] = lambda: feed
    yield SimpleNamespace(btc=btc, xmr=xmr, feed=feed)
    app.dependency_overrides.pop(get_wallets, None)
    app.dependency_overrides.pop(get_rate_feed, None)


@pytest.fixture
def card_gateway(client):
    """A Stripe stand-in, installed for one test."""
    gateway = RecordingGateway()
    app.dependency_overrides[get_gateway] = lambda: gateway
    yield gateway
    app.dependency_overrides.pop(get_gateway, None)


def place_order(client, register, create_restaurant, *, price=12.5, quantity=2, tip=3.0):
    """A customer, a kitchen, and an order with a known bill."""
    _, headers = register()
    restaurant = create_restaurant(headers, name="Crypto Kitchen")
    saved = client.put(
        f"/api/restaurants/{restaurant['restaurant_id']}/menu",
        json=[
            {
                "item_id": "item_pizza",
                "name": "Margherita",
                "price": price,
                "is_available": True,
            }
        ],
        headers=headers,
    )
    assert saved.status_code == 200, saved.text

    response = client.post(
        "/api/orders",
        json={
            "restaurant_id": restaurant["restaurant_id"],
            "items": [{"item_id": "item_pizza", "quantity": quantity}],
            "delivery_address": "9 Customer Rd",
            "tip_amount": tip,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return {"headers": headers, "order": response.json()}


def invoice(client, headers, order_id, asset=ASSET_BTC):
    return client.post(
        "/api/payments/crypto/invoice",
        json={"order_id": order_id, "asset": asset},
        headers=headers,
    )


def read_status(client, headers, order_id):
    return client.get(f"/api/payments/crypto/status/{order_id}", headers=headers)


def order_payment_status(client, headers, order_id):
    response = client.get(f"/api/orders/{order_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["payment_status"]


# ---------------------------------------------------------------------------
# What can be paid with
# ---------------------------------------------------------------------------


def test_methods_says_crypto_is_off_when_no_wallet_is_configured(client):
    """A deployment with no wallet offers cards only, and says so without
    pretending the feature failed."""
    body = client.get("/api/payments/methods").json()

    assert body["crypto"]["enabled"] is False
    assert body["crypto"]["assets"] == []
    # No Stripe key in the test environment either.
    assert body["card_available"] is False


def test_methods_lists_both_assets_with_their_confirmation_policy(client, wallets):
    body = client.get("/api/payments/methods").json()

    assert body["crypto"]["enabled"] is True
    assets = {asset["code"]: asset for asset in body["crypto"]["assets"]}
    assert set(assets) == {ASSET_BTC, ASSET_XMR}
    assert assets[ASSET_BTC]["confirmations_required"] == 1
    assert assets[ASSET_XMR]["confirmations_required"] == 2
    assert assets[ASSET_BTC]["unit"] == "BTC"
    assert assets[ASSET_BTC]["minimum"] == "0.00001"


def test_one_configured_asset_does_not_advertise_the_other(client):
    only_btc = FakeWallet(ASSET_BTC)
    app.dependency_overrides[get_wallets] = lambda: CryptoWallets({ASSET_BTC: only_btc})
    try:
        body = client.get("/api/payments/methods").json()
    finally:
        app.dependency_overrides.pop(get_wallets, None)

    assert [asset["code"] for asset in body["crypto"]["assets"]] == [ASSET_BTC]


# ---------------------------------------------------------------------------
# Issuing an invoice
# ---------------------------------------------------------------------------


def test_an_invoice_quotes_the_stored_bill(client, wallets, register, create_restaurant):
    world = place_order(client, register, create_restaurant)

    response = invoice(client, world["headers"], world["order"]["order_id"])

    assert response.status_code == 201, response.text
    body = response.json()
    # $30.99 at $60,000 a coin.
    assert body["amount_atomic"] == 51_650
    assert body["amount"] == "0.0005165"
    assert body["fiat_total_cents"] == TOTAL_CENTS
    assert body["rate_cents_per_coin"] == BTC_RATE_CENTS
    assert body["confirmations_required"] == 1
    assert body["address"] == wallets.btc.addresses[0]
    assert body["uri"] == f"bitcoin:{body['address']}?amount=0.0005165"
    assert body["status"] == "awaiting"
    # The wallet was told which order it is for, so an operator can find it.
    assert wallets.btc.labels == [world["order"]["order_id"]]


def test_monero_is_quoted_in_piconero_with_its_own_uri(
    client, wallets, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)

    body = invoice(
        client, world["headers"], world["order"]["order_id"], asset=ASSET_XMR
    ).json()

    # $30.99 at $150 a coin.
    assert body["amount_atomic"] == 206_600_000_000
    assert body["amount"] == "0.2066"
    assert body["confirmations_required"] == 2
    assert body["uri"] == f"monero:{body['address']}?tx_amount=0.2066"


def test_the_quote_rounds_up_so_the_bill_can_always_be_paid(
    client, wallets, register, create_restaurant
):
    """Rounding to nearest would sometimes ask for a fraction less than the bill,
    and an invoice short by a satoshi is one that cannot be settled."""
    wallets.feed.rates[ASSET_BTC] = 6_500_000  # $65,000
    world = place_order(client, register, create_restaurant)

    body = invoice(client, world["headers"], world["order"]["order_id"]).json()

    exact = TOTAL_CENTS * 100_000_000 / 6_500_000
    assert body["amount_atomic"] == 47_677
    assert body["amount_atomic"] > exact  # rounded up, never down


def test_asking_again_hands_back_the_address_already_given_out(
    client, wallets, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)

    first = invoice(client, world["headers"], world["order"]["order_id"]).json()
    second = invoice(client, world["headers"], world["order"]["order_id"]).json()

    assert second["invoice_id"] == first["invoice_id"]
    assert second["address"] == first["address"]
    assert len(wallets.btc.addresses) == 1


def test_the_quote_expires_in_fifteen_minutes_by_default(
    client, wallets, register, create_restaurant
):
    before = datetime.now(timezone.utc)
    world = place_order(client, register, create_restaurant)

    body = invoice(client, world["headers"], world["order"]["order_id"]).json()

    expires = datetime.fromisoformat(body["expires_at"])
    grace = datetime.fromisoformat(body["grace_until"])
    # The clock starts on the server after this request left, so the window is
    # fifteen minutes plus however long the request itself took.
    assert timedelta(minutes=14) < expires - before < timedelta(minutes=15, seconds=30)
    # The grace window belongs to the watcher, not to the customer: it outlives
    # the quote by the configured hours, because late money is still money.
    assert grace - expires == timedelta(hours=24)


def test_the_quote_times_are_sent_as_utc(client, wallets, register, create_restaurant):
    """SQLite stores these naive; the browser must not read them as local time.

    A countdown built from an offset-less timestamp starts hours off in most
    timezones, which is exactly long enough for a customer to think they still
    have time on a quote that expired.
    """
    world = place_order(client, register, create_restaurant)
    order_id = world["order"]["order_id"]

    for body in (
        invoice(client, world["headers"], order_id).json(),
        read_status(client, world["headers"], order_id).json(),
    ):
        for key in ("expires_at", "grace_until"):
            stamp = datetime.fromisoformat(body[key])
            assert stamp.utcoffset() == timedelta(0), (key, body[key])


def test_a_second_asset_cannot_open_a_second_address(
    client, wallets, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    invoice(client, world["headers"], world["order"]["order_id"], asset=ASSET_BTC)

    response = invoice(
        client, world["headers"], world["order"]["order_id"], asset=ASSET_XMR
    )

    assert response.status_code == 409
    assert "Bitcoin invoice is already open" in response.json()["detail"]
    assert wallets.xmr.addresses == []


def test_only_the_customer_may_invoice_an_order(
    client, wallets, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    _, other_headers = register()

    stranger = invoice(client, other_headers, world["order"]["order_id"])
    missing = invoice(client, other_headers, "order_does_not_exist")

    assert stranger.status_code == 403
    assert missing.status_code == 404


def test_an_unknown_asset_is_refused_by_name(client, wallets, register, create_restaurant):
    world = place_order(client, register, create_restaurant)

    response = invoice(client, world["headers"], world["order"]["order_id"], asset="doge")

    assert response.status_code == 400
    assert "btc" in response.json()["detail"]
    assert "xmr" in response.json()["detail"]


def test_the_quote_ignores_anything_the_client_says_about_the_amount(
    client, wallets, register, create_restaurant
):
    """A doctored request can choose the asset, not the price."""
    world = place_order(client, register, create_restaurant)

    response = client.post(
        "/api/payments/crypto/invoice",
        json={
            "order_id": world["order"]["order_id"],
            "asset": ASSET_BTC,
            "amount_atomic": 1,
            "fiat_total_cents": 1,
        },
        headers=world["headers"],
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["fiat_total_cents"] == TOTAL_CENTS
    assert body["amount_atomic"] == 51_650


def test_a_paid_order_cannot_be_invoiced_again(
    client, wallets, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    body = invoice(client, world["headers"], world["order"]["order_id"]).json()
    wallets.btc.pay(body["address"], body["amount_atomic"], confirmations=1)
    read_status(client, world["headers"], world["order"]["order_id"])

    response = invoice(client, world["headers"], world["order"]["order_id"])

    assert response.status_code == 409
    assert "already paid" in response.json()["detail"]


# ---------------------------------------------------------------------------
# When it is refused
# ---------------------------------------------------------------------------


def test_no_wallet_configured_is_a_sentence_not_a_crash(
    client, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)

    response = invoice(client, world["headers"], world["order"]["order_id"])

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
    assert order_payment_status(client, world["headers"], world["order"]["order_id"]) == "pending"


def test_an_unreachable_rate_means_no_quote_rather_than_a_guess(
    client, wallets, register, create_restaurant
):
    """A stale or missing price is a wrong charge waiting to happen, so the
    invoice is refused instead of estimated."""
    wallets.feed.error = RateUnavailable("feed down")
    world = place_order(client, register, create_restaurant)

    response = invoice(client, world["headers"], world["order"]["order_id"])

    assert response.status_code == 503
    assert "exchange rate" in response.json()["detail"]
    assert wallets.btc.addresses == []


def test_a_wallet_that_cannot_issue_an_address_changes_nothing(
    client, wallets, register, create_restaurant, scalar
):
    wallets.btc.error = CryptoWalletError("node down")
    world = place_order(client, register, create_restaurant)

    response = invoice(client, world["headers"], world["order"]["order_id"])

    assert response.status_code == 503
    assert "could not issue an address" in response.json()["detail"]
    assert (
        scalar(
            "SELECT COUNT(*) FROM order_crypto_invoices WHERE order_id = ?",
            (world["order"]["order_id"],),
        )
        == 0
    )
    assert order_payment_status(client, world["headers"], world["order"]["order_id"]) == "pending"


def test_a_bill_too_small_for_the_fee_is_refused(
    client, wallets, register, create_restaurant, monkeypatch
):
    monkeypatch.setenv("CRYPTO_MIN_CHARGE_CENTS", "10000")
    world = place_order(client, register, create_restaurant, price=1.0, quantity=1, tip=0)

    response = invoice(client, world["headers"], world["order"]["order_id"])

    assert response.status_code == 400
    assert "too small" in response.json()["detail"]


def test_a_card_checkout_blocks_a_crypto_invoice(
    client, wallets, card_gateway, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    started = client.post(
        "/api/payments/checkout",
        json={"order_id": world["order"]["order_id"], "origin_url": "http://localhost:3000"},
        headers=world["headers"],
    )
    assert started.status_code == 201, started.text

    response = invoice(client, world["headers"], world["order"]["order_id"])

    assert response.status_code == 409
    assert "card checkout in progress" in response.json()["detail"]


def test_a_live_crypto_invoice_blocks_a_card_checkout(
    client, wallets, card_gateway, register, create_restaurant
):
    """Two payable pages for one bill is how a customer pays twice."""
    world = place_order(client, register, create_restaurant)
    invoice(client, world["headers"], world["order"]["order_id"])

    response = client.post(
        "/api/payments/checkout",
        json={"order_id": world["order"]["order_id"], "origin_url": "http://localhost:3000"},
        headers=world["headers"],
    )

    assert response.status_code == 409
    assert "waiting on a crypto payment" in response.json()["detail"]
    # Stripe was never asked anything: there is no session to ask about.
    assert card_gateway.created == 0
    assert card_gateway.retrieved == 0


# ---------------------------------------------------------------------------
# Watching the address
# ---------------------------------------------------------------------------


def test_a_payment_seen_but_not_confirmed_is_not_yet_paid(
    client, wallets, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    body = invoice(client, world["headers"], world["order"]["order_id"]).json()

    wallets.btc.pay(body["address"], body["amount_atomic"], confirmations=0)

    activity = read_status(
        client, world["headers"], world["order"]["order_id"]
    ).json()

    assert activity["status"] == "partial"
    assert activity["received_atomic"] == body["amount_atomic"]
    assert activity["confirmed_atomic"] == 0
    assert activity["payment_status"] == "pending"
    assert order_payment_status(client, world["headers"], world["order"]["order_id"]) == "pending"


def test_a_confirmed_payment_settles_the_order(client, wallets, register, create_restaurant):
    world = place_order(client, register, create_restaurant)
    body = invoice(client, world["headers"], world["order"]["order_id"]).json()

    wallets.btc.pay(body["address"], body["amount_atomic"], confirmations=1)

    activity = read_status(
        client, world["headers"], world["order"]["order_id"]
    ).json()

    assert activity["status"] == "confirmed"
    assert activity["payment_status"] == "paid"
    assert activity["txid"] == "tx-1"
    # The same payment row a card writes, so every other screen agrees.
    assert order_payment_status(client, world["headers"], world["order"]["order_id"]) == "paid"


def test_monero_needs_its_two_confirmations(client, wallets, register, create_restaurant):
    world = place_order(client, register, create_restaurant)
    body = invoice(
        client, world["headers"], world["order"]["order_id"], asset=ASSET_XMR
    ).json()
    wallets.xmr.readings[body["address"]] = WalletReading(
        received_atomic=body["amount_atomic"],
        confirmed_atomic=0,
        confirmations=1,
        txid="xmr-1",
    )

    one_block = read_status(client, world["headers"], world["order"]["order_id"]).json()
    assert one_block["status"] == "partial"
    assert one_block["confirmations_required"] == 2

    wallets.xmr.readings[body["address"]] = WalletReading(
        received_atomic=body["amount_atomic"],
        confirmed_atomic=body["amount_atomic"],
        confirmations=2,
        txid="xmr-1",
    )
    two_blocks = read_status(client, world["headers"], world["order"]["order_id"]).json()

    assert two_blocks["status"] == "confirmed"
    assert order_payment_status(client, world["headers"], world["order"]["order_id"]) == "paid"


def test_an_underpayment_is_not_a_payment(client, wallets, register, create_restaurant):
    world = place_order(client, register, create_restaurant)
    body = invoice(client, world["headers"], world["order"]["order_id"]).json()
    wallets.btc.pay(body["address"], body["amount_atomic"] - 1, confirmations=3)

    activity = read_status(client, world["headers"], world["order"]["order_id"]).json()

    assert activity["status"] == "partial"
    assert activity["received_atomic"] == body["amount_atomic"] - 1
    assert order_payment_status(client, world["headers"], world["order"]["order_id"]) == "pending"


def test_more_than_asked_for_is_still_paid(client, wallets, register, create_restaurant):
    world = place_order(client, register, create_restaurant)
    body = invoice(client, world["headers"], world["order"]["order_id"]).json()
    wallets.btc.pay(body["address"], body["amount_atomic"] + 5_000, confirmations=1)

    activity = read_status(client, world["headers"], world["order"]["order_id"]).json()

    assert activity["status"] == "confirmed"
    assert activity["payment_status"] == "paid"


def test_a_payment_seen_once_is_never_un_seen(
    client, wallets, register, create_restaurant
):
    """A rescanning node can report less than it did a minute ago."""
    world = place_order(client, register, create_restaurant)
    body = invoice(client, world["headers"], world["order"]["order_id"]).json()
    wallets.btc.pay(body["address"], body["amount_atomic"] - 10, confirmations=1)
    read_status(client, world["headers"], world["order"]["order_id"])

    wallets.btc.readings[body["address"]] = WalletReading()

    activity = read_status(client, world["headers"], world["order"]["order_id"]).json()
    assert activity["received_atomic"] == body["amount_atomic"] - 10


def test_the_status_of_an_invoice_is_not_public(
    client, wallets, register, create_restaurant
):
    world = place_order(client, register, create_restaurant)
    invoice(client, world["headers"], world["order"]["order_id"])
    _, other_headers = register()

    assert read_status(client, other_headers, world["order"]["order_id"]).status_code == 404
    assert read_status(client, {}, world["order"]["order_id"]).status_code == 401


def test_a_wallet_outage_does_not_report_an_unpaid_order(
    client, wallets, register, create_restaurant
):
    """The page keeps its countdown and its last known answer; a node being down
    is not news about the payment."""
    world = place_order(client, register, create_restaurant)
    body = invoice(client, world["headers"], world["order"]["order_id"]).json()
    wallets.btc.pay(body["address"], body["amount_atomic"] - 5, confirmations=2)
    read_status(client, world["headers"], world["order"]["order_id"])

    wallets.btc.error = CryptoWalletError("node down")
    response = read_status(client, world["headers"], world["order"]["order_id"])

    assert response.status_code == 200
    assert response.json()["wallet_ok"] is False
    assert response.json()["received_atomic"] == body["amount_atomic"] - 5
    assert response.json()["payment_status"] == "pending"


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def test_an_expired_quote_frees_the_card_route(client, wallets, card_gateway, register, create_restaurant, monkeypatch):
    monkeypatch.setenv("CRYPTO_QUOTE_MINUTES", "0")
    world = place_order(client, register, create_restaurant)
    invoice(client, world["headers"], world["order"]["order_id"])

    expired = read_status(client, world["headers"], world["order"]["order_id"]).json()
    assert expired["status"] == "expired"
    assert expired["payment_status"] == "failed"

    card = client.post(
        "/api/payments/checkout",
        json={"order_id": world["order"]["order_id"], "origin_url": "http://localhost:3000"},
        headers=world["headers"],
    )

    assert card.status_code == 201, card.text
    assert card_gateway.created == 1


def test_late_money_is_still_money(client, wallets, register, create_restaurant, monkeypatch):
    """A quote that expired at minute fifteen must not swallow a Bitcoin
    transaction that confirmed at minute forty."""
    monkeypatch.setenv("CRYPTO_QUOTE_MINUTES", "0")
    world = place_order(client, register, create_restaurant)
    body = invoice(client, world["headers"], world["order"]["order_id"]).json()
    assert read_status(client, world["headers"], world["order"]["order_id"]).json()["status"] == "expired"

    wallets.btc.pay(body["address"], body["amount_atomic"], confirmations=1)

    late = read_status(client, world["headers"], world["order"]["order_id"]).json()
    assert late["status"] == "confirmed"
    assert order_payment_status(client, world["headers"], world["order"]["order_id"]) == "paid"


def test_late_money_does_not_take_over_a_card_checkout(
    client, wallets, card_gateway, register, create_restaurant, monkeypatch
):
    """An expired quote, then a card page, then the old address pays.

    The card is the live attempt. The invoice records what arrived, but the
    payment row stays the card's: taking it over would leave Stripe's webhook
    with no session of its own, and the customer would have paid twice with
    nothing in the app that says so.
    """
    monkeypatch.setenv("CRYPTO_QUOTE_MINUTES", "0")
    world = place_order(client, register, create_restaurant)
    body = invoice(client, world["headers"], world["order"]["order_id"]).json()
    assert read_status(client, world["headers"], world["order"]["order_id"]).json()["status"] == "expired"

    card = client.post(
        "/api/payments/checkout",
        json={
            "order_id": world["order"]["order_id"],
            "origin_url": "http://localhost:3000",
        },
        headers=world["headers"],
    )
    assert card.status_code == 201, card.text

    wallets.btc.pay(body["address"], body["amount_atomic"], confirmations=1)
    late = read_status(client, world["headers"], world["order"]["order_id"]).json()

    # The money is visible and the invoice is confirmed...
    assert late["status"] == "confirmed"
    assert late["received_atomic"] == body["amount_atomic"]
    # ...but the order is not marked paid by it, because the card still owns the
    # payment row and is still open.
    assert late["payment_status"] == "pending"
    assert card_gateway.created == 1


def test_an_expired_invoice_can_be_replaced(client, wallets, register, create_restaurant, monkeypatch):
    monkeypatch.setenv("CRYPTO_QUOTE_MINUTES", "0")
    world = place_order(client, register, create_restaurant)
    first = invoice(client, world["headers"], world["order"]["order_id"]).json()
    read_status(client, world["headers"], world["order"]["order_id"])

    second = invoice(client, world["headers"], world["order"]["order_id"]).json()

    assert second["invoice_id"] != first["invoice_id"]
    assert second["address"] != first["address"]
    assert len(wallets.btc.addresses) == 2


# ---------------------------------------------------------------------------
# The watcher, and the diagnostics
# ---------------------------------------------------------------------------


def test_the_watcher_settles_an_order_with_no_page_open(
    client, wallets, register, create_restaurant, monkeypatch
):
    world = place_order(client, register, create_restaurant)
    body = invoice(client, world["headers"], world["order"]["order_id"]).json()
    wallets.btc.pay(body["address"], body["amount_atomic"], confirmations=1)

    from app.database import DATABASE_URL

    @asynccontextmanager
    async def factory():
        engine = create_async_engine(DATABASE_URL)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    monkeypatch.setattr(watcher_module, "async_session_factory", factory)
    monkeypatch.setattr(
        watcher_module,
        "wallets_from_env",
        lambda environ: CryptoWallets(
            {ASSET_BTC: wallets.btc, ASSET_XMR: wallets.xmr}
        ),
    )

    checked = asyncio.run(watcher_module.run_poll_once())

    assert checked >= 1
    assert order_payment_status(client, world["headers"], world["order"]["order_id"]) == "paid"


def test_the_watcher_does_nothing_without_a_wallet(client, monkeypatch):
    monkeypatch.setattr(watcher_module, "wallets_from_env", lambda environ: None)

    assert asyncio.run(watcher_module.run_poll_once()) == 0


def test_diagnostics_reports_the_crypto_configuration(
    client, admin_user, monkeypatch
):
    """Which wallets exist, how deep a payment must be, and how many invoices
    the watcher is holding - all without asking a node anything."""
    _, admin_headers = admin_user()
    monkeypatch.setenv("BITCOIN_RPC_URL", "http://127.0.0.1:8332")

    body = client.get("/api/payments/diagnostics", headers=admin_headers).json()["crypto"]

    assert body["enabled"] is True
    assert body["assets"] == [ASSET_BTC]
    assert body["quote_minutes"] == 15
    assert body["grace_hours"] == 24
    assert body["watcher_interval_seconds"] == 30
    assert body["warnings"] == []


def test_diagnostics_calls_out_a_disabled_watcher_and_a_zero_confirmation_policy(
    client, admin_user, monkeypatch
):
    _, admin_headers = admin_user()
    monkeypatch.setenv("BITCOIN_RPC_URL", "http://127.0.0.1:8332")
    monkeypatch.setenv("CRYPTO_WATCH_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("CRYPTO_BTC_CONFIRMATIONS", "0")

    body = client.get("/api/payments/diagnostics", headers=admin_headers).json()

    warnings = " ".join(body["crypto"]["warnings"])
    assert "watcher is disabled" in warnings
    assert "no confirmations" in warnings


def test_diagnostics_says_crypto_is_off_when_no_wallet_exists(
    client, admin_user
):
    _, admin_headers = admin_user()

    body = client.get("/api/payments/diagnostics", headers=admin_headers).json()["crypto"]

    assert body["enabled"] is False
    assert any("No crypto wallet" in warning for warning in body["warnings"])
