"""
What the two wallet adapters actually send, pinned against a stub server.

`test_crypto.py` proves what this app does with a wallet's answer. This module
proves the other half: the JSON-RPC calls and the parsing, including the parts a
real node would reject if they were wrong - the `wallet/<name>` path on
bitcoind, the auth header, `create_address` parameters, and the fact that Monero
amounts arrive as strings of piconero and Bitcoin amounts as whole-coin decimal
strings.

A stub server is not a node. It pins this app's side of the conversation and
nothing about a node's behaviour; the README says the same.
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from app.crypto import CryptoWalletError
from app.crypto_wallets import BitcoinCoreWallet, MoneroWalletRpc


@pytest.fixture
def rpc_server():
    """A local HTTP server that records requests and answers from a callback."""

    state = SimpleNamespace(requests=[], responder=None, challenge=None)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the name http.server calls
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) or b"{}"
            payload = json.loads(raw)
            state.requests.append(
                {
                    "path": self.path,
                    "payload": payload,
                    "auth": self.headers.get("Authorization"),
                }
            )
            # A server that wants Digest answers anything else with a challenge,
            # which is what monero-wallet-rpc does - including to a correct
            # Basic credential.
            if state.challenge and not str(
                self.headers.get("Authorization") or ""
            ).startswith("Digest "):
                self.send_response(401)
                self.send_header("WWW-Authenticate", state.challenge)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status, body = state.responder(self.path, payload)
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):  # keep pytest's output clean
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


def answer(result=None, *, error=None):
    """A JSON-RPC response body, shaped the way both nodes shape one."""

    def responder(path, payload):
        if error is not None:
            return 200, {"result": None, "error": error, "id": payload.get("id")}
        return 200, {"result": result, "error": None, "id": payload.get("id")}

    return responder


# ---------------------------------------------------------------------------
# Bitcoin Core
# ---------------------------------------------------------------------------


def test_bitcoin_asks_the_wallet_for_an_address(rpc_server):
    rpc_server.responder = answer("bc1qstubaddress")
    wallet = BitcoinCoreWallet(
        rpc_server.url, user="rpcuser", password="rpcpass", wallet="watch"
    )

    address = asyncio.run(wallet.new_address("order_7"))

    assert address == "bc1qstubaddress"
    request = rpc_server.requests[0]
    # The wallet name is part of the path: without it bitcoind answers about
    # the default wallet, which is not the watch-only one.
    assert request["path"] == "/wallet/watch"
    assert request["payload"]["method"] == "getnewaddress"
    assert request["payload"]["params"] == ["order_7"]
    assert request["payload"]["jsonrpc"] == "1.0"
    # Basic auth, base64 of user:password.
    assert request["auth"].startswith("Basic ")


def test_bitcoin_reports_seen_and_confirmed_separately(rpc_server):
    """`getreceivedbyaddress` at depth 0 and at the policy depth is the whole
    difference between "we can see it" and "it is settled"."""
    depths = []

    def responder(path, payload):
        address, depth = payload["params"]
        depths.append(depth)
        return 200, {
            "result": "0.00051650" if depth == 0 else "0.00000000",
            "error": None,
            "id": payload["id"],
        }

    rpc_server.responder = responder
    wallet = BitcoinCoreWallet(rpc_server.url)

    reading = asyncio.run(wallet.received("bc1qaddr", confirmations=1))

    assert depths == [0, 1]
    assert reading.received_atomic == 51_650
    assert reading.confirmed_atomic == 0
    assert reading.confirmations == 0


def test_bitcoin_counts_a_settled_payment(rpc_server):
    rpc_server.responder = answer("0.00051650")
    wallet = BitcoinCoreWallet(rpc_server.url)

    reading = asyncio.run(wallet.received("bc1qaddr", confirmations=2))

    assert reading.received_atomic == 51_650
    assert reading.confirmed_atomic == 51_650
    # Best effort: bitcoind does not report per-address depth here, so the
    # adapter reports the policy depth once it is met rather than invent a count.
    assert reading.confirmations == 2


def test_bitcoin_asks_once_when_depth_zero_is_the_policy(rpc_server):
    rpc_server.responder = answer("0.00051650")
    wallet = BitcoinCoreWallet(rpc_server.url)

    reading = asyncio.run(wallet.received("bc1qaddr", confirmations=0))

    assert len(rpc_server.requests) == 1
    assert reading.confirmed_atomic == 51_650


def test_a_bitcoind_error_is_a_wallet_error(rpc_server):
    rpc_server.responder = answer(
        error={"code": -4, "message": "Wallet is not loaded."}
    )
    wallet = BitcoinCoreWallet(rpc_server.url)

    with pytest.raises(CryptoWalletError) as raised:
        asyncio.run(wallet.new_address("order_7"))

    assert "Wallet is not loaded." in str(raised.value)


def test_a_refused_login_is_a_wallet_error(rpc_server):
    rpc_server.responder = lambda path, payload: (401, {"result": None, "error": "no"})
    wallet = BitcoinCoreWallet(rpc_server.url, user="u", password="wrong")

    with pytest.raises(CryptoWalletError) as raised:
        asyncio.run(wallet.new_address("order_7"))

    assert "refused its login" in str(raised.value)


# ---------------------------------------------------------------------------
# Monero wallet RPC
# ---------------------------------------------------------------------------


def test_monero_creates_a_subaddress_for_the_invoice(rpc_server):
    rpc_server.responder = answer(
        {"address": "8StubMoneroAddress", "address_index": 12}
    )
    wallet = MoneroWalletRpc(rpc_server.url)

    address = asyncio.run(wallet.new_address("order_7"))

    assert address == "8StubMoneroAddress"
    request = rpc_server.requests[0]
    assert request["payload"]["jsonrpc"] == "2.0"
    assert request["payload"]["method"] == "create_address"
    assert request["payload"]["params"] == {"account_index": 0, "label": "order_7"}


def test_monero_sums_only_the_address_it_asked_about(rpc_server):
    rpc_server.responder = answer(
        {
            "in": [
                {
                    "address": "8Mine",
                    "amount": "100000000000",
                    "confirmations": 5,
                    "txid": "tx-deep",
                },
                {
                    "address": "8SomebodyElsesInvoice",
                    "amount": "999999999999",
                    "confirmations": 9,
                    "txid": "tx-other",
                },
                {
                    "address": "8Mine",
                    "amount": 500,
                    "confirmations": 0,
                    "txid": "tx-shallow",
                },
            ],
            "out": [],
        }
    )
    wallet = MoneroWalletRpc(rpc_server.url)

    reading = asyncio.run(wallet.received("8Mine", confirmations=2))

    assert reading.received_atomic == 100_000_000_500
    assert reading.confirmed_atomic == 100_000_000_000
    assert reading.confirmations == 5
    assert reading.txid == "tx-deep"
    assert rpc_server.requests[0]["payload"]["params"] == {
        "in": True,
        "account_index": 0,
    }


def test_monero_at_one_confirmation_does_not_settle_a_two_confirmation_policy(
    rpc_server,
):
    rpc_server.responder = answer(
        {
            "in": [
                {
                    "address": "8Mine",
                    "amount": "206600000000",
                    "confirmations": 1,
                    "txid": "tx-1",
                }
            ]
        }
    )
    wallet = MoneroWalletRpc(rpc_server.url)

    reading = asyncio.run(wallet.received("8Mine", confirmations=2))

    assert reading.received_atomic == 206_600_000_000
    assert reading.confirmed_atomic == 0
    assert reading.confirmations == 1


def test_monero_answers_a_digest_challenge_and_never_sends_basic(rpc_server):
    """The scheme matters, and a real wallet is what settled the argument.

    `monero-wallet-rpc` answered this app's Basic header with 401 to a correct
    login; its own documentation answers `--rpc-login` with `curl --digest`.
    The burn-in against a real 0.18.5.4 wallet failed on exactly this. So the
    first request carries no credential, and the wallet's challenge is answered
    with a Digest header - never with Basic.
    """
    rpc_server.challenge = (
        'Digest realm="monero-rpc", qop="auth", nonce="e2e-nonce", opaque="e2e"'
    )
    rpc_server.responder = answer({"address": "8Stub", "address_index": 1})
    wallet = MoneroWalletRpc(rpc_server.url, user="monero", password="secret")

    asyncio.run(wallet.new_address("order_7"))

    # The unauthenticated attempt that earns the challenge, then the answer.
    assert len(rpc_server.requests) == 2
    assert rpc_server.requests[0]["auth"] is None
    answered = rpc_server.requests[1]["auth"]
    assert answered.startswith("Digest ")
    assert 'username="monero"' in answered
    assert rpc_server.requests[-1]["payload"]["method"] == "create_address"


def test_an_unreachable_wallet_is_a_wallet_error():
    # Nothing is listening on port 1, which is the closest a test gets to a node
    # that is down without waiting for a timeout.
    wallet = BitcoinCoreWallet("http://127.0.0.1:1", user="u", password="p")

    with pytest.raises(CryptoWalletError):
        asyncio.run(wallet.new_address("order_7"))
