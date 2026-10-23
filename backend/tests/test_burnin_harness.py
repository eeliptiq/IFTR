"""
The burn-in harness, checked against a node that only answers.

`test_crypto_burnin.py` needs Docker, a chain and a few minutes; this module
needs none of them. It drives the harness's provisioning and payment helpers
against a scripted JSON-RPC server and asserts the sequence and the payloads
they send:

  * the watch wallet is created blank, keyless and descriptors-only, and the
    descriptor it is given the public one, ranged, and active - which is the
    whole mechanism behind "the server can derive addresses and cannot spend";
  * the miner's coins are mined to a real key and a Bitcoin payment is sent to
    the invoice's address, in the invoice's amount;
  * the Monero funder is funded with regtest blocks and pays piconero to the
    subaddress the app asked for.

What this cannot tell you is whether bitcoind and monerod agree - only the
burn-in can. It exists so that when the burn-in does run, a typo in a parameter
name or a missing `active: true` is not the first thing it discovers.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from tests.burnin_stack import (
    BTC_MINER_WALLET,
    BTC_WATCH_WALLET,
    MINED_BLOCKS,
    MONERO_FUNDING_BLOCKS,
    BitcoinNode,
    BitcoinWallets,
    Rpc,
    MoneroWallets,
    pay_bitcoin,
    pay_monero,
    provision_bitcoin,
    provision_monero,
)

DESCRIPTOR = "wpkh([d34db33f/84h/1h/0h]xpub6BurnInPublicKey/0/*)#checksum11"
MINER_ADDRESS = "bcrt1qminer000000000000000000000000000000"


class ScriptedError(Exception):
    """What a scripted answer raises to make the node refuse the call."""


@pytest.fixture
def node():
    """A JSON-RPC server that records calls and answers from a table."""
    state = SimpleNamespace(calls=[], answers={})

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802 - the name http.server calls
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            method = payload.get("method")
            params = payload.get("params")

            wallet = ""
            if self.path.startswith("/wallet/"):
                wallet = self.path.split("/wallet/", 1)[1]

            state.calls.append(
                SimpleNamespace(method=method, params=params, wallet=wallet)
            )

            answer = state.answers.get(method)
            if answer is None:
                body = {"result": None, "error": {"code": -32601, "message": method}}
            elif callable(answer):
                try:
                    body = {"result": answer(params, wallet), "error": None}
                except ScriptedError as exc:
                    body = {"result": None, "error": {"code": -4, "message": str(exc)}}
            else:
                body = {"result": answer, "error": None}
            body["id"] = payload.get("id")

            encoded = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def calls_to(node, method):
    return [call for call in node.calls if call.method == method]


# ---------------------------------------------------------------------------
# Bitcoin: the descriptor that makes a keyless wallet useful
# ---------------------------------------------------------------------------


def test_the_watch_wallet_gets_the_public_descriptor_ranged_and_active(node):
    node.answers = {
        "createwallet": {"name": "wallet", "warning": ""},
        "getrawchangeaddress": MINER_ADDRESS,
        "generatetoaddress": ["block-hash"],
        "listdescriptors": {
            "descriptors": [
                {"desc": "wpkh([x/0/*)#change", "active": True, "internal": True},
                {"desc": DESCRIPTOR, "active": True, "internal": False},
            ]
        },
        "importdescriptors": [{"success": True}],
        "getwalletinfo": {"private_keys_enabled": False},
    }

    wallets = provision_bitcoin(BitcoinNode(node.url))

    assert wallets.mining_address == MINER_ADDRESS

    # The miner exists, is descriptor-based, and its coins are mined to a key.
    created = calls_to(node, "createwallet")
    assert created[0].params["wallet_name"] == BTC_MINER_WALLET
    assert created[0].params["descriptors"] is True

    # The coins go to a change address, which the watch wallet never derives
    # invoice addresses for: an invoice must not be an address that already
    # holds the miner's coinbase.
    assert not calls_to(node, "getnewaddress")
    mined_to = calls_to(node, "getrawchangeaddress")[0]
    assert mined_to.wallet == BTC_MINER_WALLET

    mined = calls_to(node, "generatetoaddress")
    assert mined[0].params == {"address": MINER_ADDRESS, "nblocks": MINED_BLOCKS}
    assert mined[0].wallet == BTC_MINER_WALLET

    # The watch wallet: no keys, no default descriptors, and the miner's
    # receive descriptor imported as active with room to derive from.
    watch = created[1].params
    assert watch["wallet_name"] == BTC_WATCH_WALLET
    assert watch["disable_private_keys"] is True
    assert watch["blank"] is True
    assert watch["descriptors"] is True

    imported = calls_to(node, "importdescriptors")[0]
    assert imported.wallet == BTC_WATCH_WALLET
    request = imported.params["requests"][0]
    assert request["desc"] == DESCRIPTOR
    assert request["active"] is True
    assert request["internal"] is False
    assert request["range"] == [0, 200]
    assert request["timestamp"] == "now"

    # The last thing the harness does is check the claim it just made.
    info = calls_to(node, "getwalletinfo")[0]
    assert info.wallet == BTC_WATCH_WALLET


def test_provisioning_refuses_a_watch_wallet_that_has_private_keys(node):
    """A wallet that can spend is not the wallet the README describes."""
    node.answers = {
        "createwallet": {"name": "wallet", "warning": ""},
        "getrawchangeaddress": MINER_ADDRESS,
        "generatetoaddress": ["block-hash"],
        "listdescriptors": {
            "descriptors": [{"desc": DESCRIPTOR, "active": True, "internal": False}]
        },
        "importdescriptors": [{"success": True}],
        "getwalletinfo": {"private_keys_enabled": True},
    }

    with pytest.raises(AssertionError) as raised:
        provision_bitcoin(BitcoinNode(node.url))

    assert "private keys" in str(raised.value)


def test_a_bitcoin_payment_sends_the_invoice_amount_and_confirms_it(node):
    node.answers = {
        "sendtoaddress": "txid-paid",
        "generatetoaddress": ["block-hash"],
    }
    wallets = BitcoinWallets(mining_address=MINER_ADDRESS)
    bitcoin = BitcoinNode(node.url)

    txid = pay_bitcoin(bitcoin, wallets, "bcrt1qinvoice", "0.0005165")

    assert txid == "txid-paid"
    sent = calls_to(node, "sendtoaddress")[0]
    assert sent.wallet == BTC_MINER_WALLET
    # The amount is the invoice's, to the satoshi, and the address is the one
    # the app derived - not a fresh one of the wallet's choosing.
    assert sent.params["address"] == "bcrt1qinvoice"
    assert round(sent.params["amount"] * 100_000_000) == 51_650

    mined = calls_to(node, "generatetoaddress")[0]
    assert mined.params == {"address": MINER_ADDRESS, "nblocks": 1}


# ---------------------------------------------------------------------------
# Monero: two wallets, funded by regtest blocks
# ---------------------------------------------------------------------------


def test_the_funder_is_funded_with_regtest_blocks(node):
    node.answers = {
        "create_wallet": {},
        "get_address": {"address": "8funderAddress", "address_index": 0},
        "generateblocks": {"blocks": []},
        "refresh": {},
        "get_balance": {"unlocked_balance": 5_000_000_000_000},
    }

    wallets = provision_monero(
        Rpc(node.url + "/json_rpc"),
        Rpc(node.url + "/json_rpc"),
        Rpc(node.url + "/json_rpc"),
    )

    assert wallets.funder_address == "8funderAddress"
    assert [call.params["filename"] for call in calls_to(node, "create_wallet")] == [
        "iftr-merchant",
        "iftr-funder",
    ]

    blocks = calls_to(node, "generateblocks")[0].params
    assert blocks["wallet_address"] == "8funderAddress"
    assert blocks["amount_of_blocks"] == MONERO_FUNDING_BLOCKS


def test_a_monero_payment_is_piconero_to_the_subaddress(node):
    node.answers = {
        "transfer": {"tx_hash": "xmr-txid"},
        "generateblocks": {"blocks": []},
    }
    wallets = MoneroWallets(
        merchant=Rpc(node.url + "/json_rpc"),
        funder=Rpc(node.url + "/json_rpc"),
        funder_address="8funderAddress",
    )

    txid = pay_monero(
        Rpc(node.url + "/json_rpc"), wallets, "8invoiceSubaddress", 206_600_000_000
    )

    assert txid == "xmr-txid"
    sent = calls_to(node, "transfer")[0].params
    assert sent["account_index"] == 0
    assert sent["destinations"] == [
        {"address": "8invoiceSubaddress", "amount": 206_600_000_000}
    ]

    # Three regtest blocks for a two-confirmation policy, mined to the funder.
    blocks = calls_to(node, "generateblocks")[0].params
    assert blocks == {
        "amount_of_blocks": 3,
        "wallet_address": "8funderAddress",
        "starting_nonce": 0,
    }


def test_a_wallet_that_already_exists_is_opened_instead_of_recreated(node):
    """A second run against the same container must not die on "exists"."""
    state = {"created": 0}

    def create_wallet(params, wallet):
        state["created"] += 1
        if state["created"] == 2:
            raise ScriptedError("Wallet already exists: iftr-funder")
        return {}

    node.answers = {
        "create_wallet": create_wallet,
        "open_wallet": {},
        "get_address": {"address": "8funderAddress"},
        "generateblocks": {},
        "refresh": {},
        "get_balance": {"unlocked_balance": 1},
    }

    provision_monero(
        Rpc(node.url + "/json_rpc"),
        Rpc(node.url + "/json_rpc"),
        Rpc(node.url + "/json_rpc"),
    )

    # The funder's second call reported "exists", so the harness opened it
    # rather than failing a run that was only repeating itself.
    assert state["created"] == 2
    opened = calls_to(node, "open_wallet")
    assert [call.params["filename"] for call in opened] == ["iftr-funder"]
