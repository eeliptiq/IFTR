"""
Paying a real invoice from a real chain, without the page open.

Everything else in the crypto suite is a fake: `test_crypto.py` uses wallets
that have a memory, `test_crypto_wallets.py` a stub server. This module is the
one run that talks to a bitcoind and a monerod that have a chain, derive real
addresses, and need real blocks before money is final.

It is opt-in - `RUN_CRYPTO_BURNIN=1`, with Docker on the machine - because it
pulls images and starts four containers. The claims it exists to check:

  * a blank, keyless Bitcoin wallet accepts this app's descriptor import, and
    `getnewaddress` on it returns addresses the node actually scans;
  * `monerod --regtest` and wallet RPC agree about a subaddress payment, so the
    two-confirmation policy settles when it should;
  * the **background watcher**, not the payment page, is enough: the tests never
    poll `/api/payments/crypto/status` for settlement, they poll the order;
  * a short payment is seen and does not settle, which is the difference between
    "we can see it" and "it is paid".

What it still cannot prove: that a mainnet wallet behaves the same way. Regtest
has no reorgs worth the name and no fee market; those stay in the README's list
of things this is not.
"""

import time
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from tests.burnin_stack import (
    BTC_WATCH_WALLET,
    COMPOSE_FILE,
    BurnIn,
    JsonRpcError,
    pay_bitcoin,
    pay_monero,
    skip_reason,
)

PASSWORD = "passw0rd123"

# One block to confirm a Bitcoin payment, two for Monero, plus the wallet
# catching up and the watcher's own interval. Three minutes is a generous bound
# on a machine that has just pulled four images.
SETTLE_TIMEOUT = 180


# ---------------------------------------------------------------------------
# The compose file, checked whether or not Docker is here
# ---------------------------------------------------------------------------


def test_the_compose_file_is_the_stack_the_harness_expects():
    """The harness drives this file by name; drift between them should fail fast.

    Parsing it is cheap and needs no daemon, so this test runs in every suite -
    including the ones on a machine that will never start a container. It cannot
    tell you the containers work; that is what the rest of the module is for.
    """
    yaml = pytest.importorskip("yaml")
    document = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    services = document["services"]

    assert {"bitcoin", "monerod", "monero-merchant", "monero-funder"} <= set(services)

    bitcoin = " ".join(services["bitcoin"]["command"])
    assert "-regtest=1" in bitcoin
    # Without a fallback fee, regtest refuses to send anything at all.
    assert "-fallbackfee" in bitcoin

    daemon = " ".join(services["monerod"]["command"])
    assert "--regtest" in daemon
    # Instant blocks are the only reason a regtest payment test is affordable.
    assert "--fixed-difficulty=1" in daemon
    # The daemon is unauthenticated on purpose: 0.18.5.4 answered 401 to a
    # correct Basic credential when `--rpc-login` was set, so the harness does
    # not depend on a flag that could not be verified. It is loopback-only and
    # on the test network; the wallet daemons keep their own login.
    assert "--rpc-login" not in daemon

    # Flags the image's entrypoint already supplies. Twice is fatal, not
    # redundant: monerod parses its options and exits with "option
    # '--non-interactive' cannot be specified more than once" before it binds a
    # port, so every wait after it times out on a refused connection and says
    # nothing about the cause. The first CI run of this harness failed that way.
    assert "--non-interactive" not in daemon

    for name in ("monero-merchant", "monero-funder"):
        command = " ".join(services[name]["command"])
        assert "--daemon-host=monerod" in command
        assert "--wallet-dir" in command
        # monerod owns the network; wallet RPC has no --regtest flag and learns
        # the network from the daemon it connects to.
        assert "--regtest" not in command
        # Same trap: the wallet entrypoint adds both as soon as it sees
        # --rpc-login, and a duplicate makes the daemon exit before it binds.
        assert "--rpc-bind-ip" not in command, name
        assert "--confirm-external-bind" not in command, name
        # The login is what makes the entrypoint bind 0.0.0.0 and publish it.
        assert "--rpc-login" in command, name

    # A floating tag turns a burn-in red for a reason that has nothing to do
    # with this app, which is the opposite of what a burn-in is for. The images
    # are versioned; the defaults use the version.
    for name in ("monerod", "monero-merchant", "monero-funder"):
        image = str(services[name]["image"])
        assert not image.endswith(":latest"), (name, image)
        assert "v0.18.5.4" in image, (name, image)

    # One wallet open per daemon is why there are two: they must not share a
    # directory, or the second would take the first's wallet.
    assert services["monero-merchant"]["volumes"] != services["monero-funder"]["volumes"]

    # These wallets hold test coins, but a published RPC port on anything other
    # than loopback is still a mistake worth catching here.
    for name, service in services.items():
        for mapping in service.get("ports", []):
            assert str(mapping).startswith("127.0.0.1:"), (name, mapping)


# ---------------------------------------------------------------------------
# The stack
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stack():
    reason = skip_reason()
    if reason:
        pytest.skip(reason)

    burn = BurnIn()
    try:
        burn.start_containers()
        burn.start_api()
        yield burn
    finally:
        # Keep what the containers said: a failing burn-in is usually a
        # provisioning problem, and the details are in those logs.
        burn.dump_container_logs()
        burn.stop()


@pytest.fixture(scope="module")
def world(stack):
    """A customer, a kitchen and a one-dish menu, all through the real API."""
    with httpx.Client(base_url=stack.api_url, timeout=60) as client:
        customer = client.post(
            "/api/auth/register",
            json={
                "email": f"burnin-customer-{time.time_ns()}@example.com",
                "password": PASSWORD,
                "name": "Burn-in Customer",
                "role": "customer",
            },
        )
        assert customer.status_code == 201, customer.text
        customer_headers = {
            "Authorization": f"Bearer {customer.json()['access_token']}"
        }

        owner = client.post(
            "/api/auth/register",
            json={
                "email": f"burnin-owner-{time.time_ns()}@example.com",
                "password": PASSWORD,
                "name": "Burn-in Kitchen",
                "role": "restaurant_admin",
            },
        )
        assert owner.status_code == 201, owner.text
        owner_headers = {"Authorization": f"Bearer {owner.json()['access_token']}"}

        restaurant = client.post(
            "/api/restaurants",
            json={
                "name": "Regtest Kitchen",
                "description": "",
                "cuisine_type": "italian",
                "image_url": None,
                "lat": 40.7,
                "lng": -74.0,
                "address": "1 Regtest St",
                "city": "NYC",
                "zip_code": "10001",
            },
            headers=owner_headers,
        )
        assert restaurant.status_code == 201, restaurant.text
        restaurant_id = restaurant.json()["restaurant_id"]

        menu = client.put(
            f"/api/restaurants/{restaurant_id}/menu",
            json=[
                {
                    "item_id": "item_burnin",
                    "name": "Regtest Pizza",
                    "price": 12.5,
                    "is_available": True,
                }
            ],
            headers=owner_headers,
        )
        assert menu.status_code == 200, menu.text

        yield SimpleNamespace(
            client=client,
            headers=customer_headers,
            restaurant_id=restaurant_id,
        )


@dataclass
class Order:
    """One order and the invoice opened for it."""

    order_id: str
    invoice: dict

    @property
    def address(self) -> str:
        return self.invoice["address"]

    @property
    def amount(self) -> str:
        return self.invoice["amount"]

    @property
    def amount_atomic(self) -> int:
        return self.invoice["amount_atomic"]


def place_order(world, asset: str) -> Order:
    """An order with a known bill, then an invoice for it."""
    client = world.client
    created = client.post(
        "/api/orders",
        json={
            "restaurant_id": world.restaurant_id,
            "items": [{"item_id": "item_burnin", "quantity": 2}],
            "delivery_address": "9 Customer Rd",
            "tip_amount": 3.0,
        },
        headers=world.headers,
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]

    invoice = client.post(
        "/api/payments/crypto/invoice",
        json={"order_id": order_id, "asset": asset},
        headers=world.headers,
    )
    assert invoice.status_code == 201, invoice.text
    return Order(order_id=order_id, invoice=invoice.json())


def eventually(probe, *, timeout: float, describe: str, interval: float = 1.0):
    """Poll a live API until `probe` returns something truthy, or say what it saw.

    Interval and timeout are not decoration: this is waiting on a chain and on a
    background task, so the failure message has to be the last answer, not just
    a timeout.
    """
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = probe()
        if last:
            return last
        time.sleep(interval)

    raise AssertionError(f"{describe}; last answer: {last!r}")


def wait_until_paid(world, order: Order) -> dict:
    """The order endpoint, not the crypto status endpoint: the watcher's work."""

    def probe():
        response = world.client.get(
            f"/api/orders/{order.order_id}", headers=world.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        return body if body["payment_status"] == "paid" else None

    return eventually(
        probe,
        timeout=SETTLE_TIMEOUT,
        describe=f"order {order.order_id} was never marked paid by the watcher",
    )


# ---------------------------------------------------------------------------
# Bitcoin
# ---------------------------------------------------------------------------


def test_a_bitcoin_invoice_is_paid_by_a_real_node(stack, world):
    """From a watch-only descriptor to a paid order, with no page polling."""
    order = place_order(world, "btc")
    assert order.address.startswith("bcrt1"), order.address
    # The miner's coins live on a change address the invoice chain never
    # reaches, so a settled invoice really was paid and not just holding the
    # coinbase from provisioning.
    assert order.address != stack.btc_wallets.mining_address

    # The wallet the app is configured with is supposed to hold no keys. If that
    # ever stops being true, every "the server cannot move your money" claim in
    # the README stops being true with it.
    watch_info = stack.bitcoin.call("getwalletinfo", wallet=BTC_WATCH_WALLET)
    assert watch_info["private_keys_enabled"] is False

    pay_bitcoin(stack.bitcoin, stack.btc_wallets, order.address, order.amount)

    paid = wait_until_paid(world, order)
    assert paid["total_amount"] == pytest.approx(order.invoice["fiat_total_cents"] / 100)

    # The chain agrees with the order: the address the app derived really did
    # receive the invoice amount, confirmed.
    received = stack.bitcoin.call(
        "getreceivedbyaddress",
        {"address": order.address, "minconf": 1},
        wallet=BTC_WATCH_WALLET,
    )
    assert Decimal(str(received)) * 100_000_000 == order.amount_atomic

    status = world.client.get(
        f"/api/payments/crypto/status/{order.order_id}", headers=world.headers
    ).json()
    assert status["status"] == "confirmed"
    assert status["received_atomic"] == order.amount_atomic
    assert status["payment_status"] == "paid"


def test_a_short_bitcoin_payment_is_seen_and_does_not_settle(stack, world):
    """Half an invoice is a partial payment, not a paid order.

    This is the case a customer creates by typing an amount by hand, and the one
    where a bug that rounds, or that trusts "some money arrived", charges someone
    for an order they did not pay for.
    """
    order = place_order(world, "btc")
    half = (Decimal(order.amount) / 2).quantize(Decimal("0.00000001"))
    assert half > 0

    pay_bitcoin(stack.bitcoin, stack.btc_wallets, order.address, str(half))

    def seen():
        response = world.client.get(
            f"/api/payments/crypto/status/{order.order_id}", headers=world.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        return body if body["received_atomic"] > 0 else None

    status = eventually(
        seen,
        timeout=SETTLE_TIMEOUT,
        describe=f"the node never reported the partial payment for {order.order_id}",
    )
    assert status["received_atomic"] < order.amount_atomic
    assert status["status"] == "partial"

    # And the order is still unpaid: nobody may deliver on half a bill.
    state = world.client.get(
        f"/api/orders/{order.order_id}", headers=world.headers
    ).json()
    assert state["payment_status"] != "paid"


# ---------------------------------------------------------------------------
# Monero
# ---------------------------------------------------------------------------


def test_a_monero_invoice_is_paid_by_a_real_node(stack, world):
    """A subaddress payment, two regtest blocks, and the watcher's settlement."""
    order = place_order(world, "xmr")
    # Regtest uses the mainnet address format, and `create_address` returns a
    # subaddress - the "8..." form - which is what a fresh address per invoice
    # has to be.
    assert order.address.startswith("8"), order.address

    txid = pay_monero(
        stack.xmr_daemon, stack.monero, order.address, order.amount_atomic
    )
    assert txid

    # Wallet RPC refreshes on its own schedule; asking it once removes that
    # variable from a test that is about the watcher, not about refresh timing.
    stack.monero.merchant.call("refresh")

    paid = wait_until_paid(world, order)
    assert paid["total_amount"] == pytest.approx(order.invoice["fiat_total_cents"] / 100)

    status = world.client.get(
        f"/api/payments/crypto/status/{order.order_id}", headers=world.headers
    ).json()
    assert status["status"] == "confirmed"
    assert status["received_atomic"] == order.amount_atomic
    # The adapter reports the deepest transfer it saw; two blocks were mined for
    # a two-confirmation policy, so it cannot be zero.
    assert status["confirmations"] >= 2
    assert status["txid"]


# ---------------------------------------------------------------------------
# What the harness needs in order to fail usefully
# ---------------------------------------------------------------------------


def test_the_harness_reports_a_node_it_cannot_reach():
    """A wrong port must be an error with the node's words, not a hang.

    This is the only test here that runs without the stack, and it is here
    because a burn-in whose failure mode is a three-minute timeout is a burn-in
    nobody trusts twice.
    """
    from tests.burnin_stack import Rpc

    with pytest.raises(JsonRpcError) as raised:
        Rpc("http://127.0.0.1:1", user="u", password="p", timeout=2.0).call(
            "get_info"
        )

    assert "could not be reached" in str(raised.value)
