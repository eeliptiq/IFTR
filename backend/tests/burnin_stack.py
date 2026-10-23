"""
Real nodes, real chain: the part the stub tests cannot prove.

`test_crypto.py` runs the invoice flow against wallets that have a memory, and
`test_crypto_wallets.py` pins this app's JSON-RPC calls against a stub server.
Neither can tell you that a real bitcoind accepts the watch-only descriptor the
app derives addresses from, that `monerod --regtest` reports depth the way the
adapter reads it, or that the background watcher settles an order nobody is
looking at. This module builds the thing that can.

What it starts, via `backend/burnin/compose.yaml`:

  * **bitcoind** on regtest, with two wallets: `iftr-miner` (real keys, the
    stand-in for the merchant's hardware wallet) and `iftr-watch` (blank,
    `disable_private_keys`, with the miner's *public* ranged descriptor
    imported). The app is pointed at the watch wallet, so every address it asks
    this node for is one a real wallet derived and will really scan for.
  * **monerod** on regtest, offline, with `--fixed-difficulty=1`, so blocks are
    mined on demand instead of waited for.
  * **two wallet-RPC daemons**: the merchant's (the app's) and a funder's (the
    customer's). They are separate processes on purpose - one `monero-wallet-rpc`
    can only have one wallet open, and the app must keep its wallet open while
    the test spends from another.

Then it starts the real API with those endpoints in its environment, so the
lifespan starts the real watcher. The tests pay the invoices from the nodes and
wait for `GET /api/orders/{id}` to say paid: no page poll, no fake rate, no stub.

Opt-in, because it needs Docker: `RUN_CRYPTO_BURNIN=1`. Without it the module
skips with a sentence, and the only test that still runs is the one that checks
the compose file says what this module expects of it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Callable, Dict, List, Optional

import httpx

from tests.processes import free_port, spawn, stop, tail, wait_for

# tests/ -> backend/ -> Evolved/
BACKEND = Path(__file__).resolve().parents[1]
COMPOSE_FILE = BACKEND / "burnin" / "compose.yaml"
LOG_DIR = BACKEND / "logs" / "burnin"

# Regtest credentials. They are worth nothing and exist only inside containers
# published to loopback; never copy this shape into a deployment.
BTC_USER = "burnin"
BTC_PASSWORD = "burnin"
MONERO_USER = "burnin"
MONERO_PASSWORD = "burnin"

# Fixed names, because the harness provisions them by name over RPC.
BTC_MINER_WALLET = "iftr-miner"
BTC_WATCH_WALLET = "iftr-watch"
XMR_MERCHANT_WALLET = "iftr-merchant"
XMR_FUNDER_WALLET = "iftr-funder"

# What the burn-in quotes at. The rate feed is a local stub: reaching CoinGecko
# from a test would make it depend on the internet and on a price.
RATES = {"bitcoin": {"usd": 60000}, "monero": {"usd": 150}}

# Regtest Bitcoin is cheap but not free of rules: `sendtoaddress` needs a fee it
# can fall back on, and the coinbase it spends matures after 100 blocks.
MINED_BLOCKS = 101

# Monero's coinbase outputs are locked for 60 blocks; 70 leaves a margin, and
# `--fixed-difficulty=1` makes generating them a second's work.
MONERO_FUNDING_BLOCKS = 70

# Mining on regtest is supposed to be instant and is not always: 101 blocks took
# four minutes on a Windows laptop and a second on Linux. The HTTP call waits for
# the work rather than failing a correct run because a disk is slow.
BTC_MINING_TIMEOUT = 900.0
MONERO_MINING_TIMEOUT = 600.0

# Deriving a few hundred descriptor addresses is quick on Linux and was not on
# Windows; the call that does it waits for the node rather than for a guess.
DESCRIPTOR_IMPORT_TIMEOUT = 600.0


class JsonRpcError(RuntimeError):
    """A node answered the call and refused it, or answered with nonsense."""


class Rpc:
    """Just enough JSON-RPC to drive two nodes and two wallets.

    Bitcoin speaks 1.0 and puts the wallet name in the URL path; Monero speaks
    2.0 at `/json_rpc`. Both answer `{"result": ...}` or `{"error": ...}`, which
    is the whole of what this class relies on.
    """

    def __init__(
        self,
        url: str,
        *,
        user: str = "",
        password: str = "",
        version: str = "2.0",
        timeout: float = 60.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.version = version
        self.timeout = timeout
        self._auth = (user, password) if user or password else None

    def call(
        self,
        method: str,
        params: Any = None,
        *,
        path: str = "",
        timeout: Optional[float] = None,
    ) -> Any:
        body: Dict[str, Any] = {
            "jsonrpc": self.version,
            "id": f"burnin-{method}",
            "method": method,
        }
        if params is not None:
            body["params"] = params

        try:
            response = httpx.post(
                f"{self.url}{path}",
                json=body,
                auth=self._auth,
                timeout=timeout or self.timeout,
            )
        except httpx.HTTPError as exc:
            raise JsonRpcError(f"{method}: the node could not be reached: {exc}") from exc

        if response.status_code >= 400:
            raise JsonRpcError(
                f"{method}: HTTP {response.status_code}: {response.text[:400]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise JsonRpcError(f"{method}: the node answered with something else") from exc

        if not isinstance(payload, dict):
            raise JsonRpcError(f"{method}: the node answered with something else")

        if payload.get("error"):
            raise JsonRpcError(f"{method}: {payload['error']}")

        if "result" not in payload:
            raise JsonRpcError(f"{method}: the node answered without a result")

        return payload["result"]


class BitcoinNode:
    """bitcoind, with the wallet name folded into the path."""

    def __init__(self, url: str) -> None:
        self.rpc = Rpc(url, user=BTC_USER, password=BTC_PASSWORD, version="1.0")

    def call(
        self,
        method: str,
        params: Any = None,
        *,
        wallet: str = "",
        timeout: Optional[float] = None,
    ) -> Any:
        path = f"/wallet/{wallet}" if wallet else ""
        return self.rpc.call(method, params, path=path, timeout=timeout)

    def wait_ready(self, timeout: float = 180.0) -> None:
        wait_until(
            lambda: self.call("getblockchaininfo")["chain"] == "regtest",
            timeout=timeout,
            describe="bitcoind regtest was not ready",
        )


@dataclass
class BitcoinWallets:
    """Where the miner's coins go, so a payment can be confirmed."""

    mining_address: str


@dataclass
class MoneroWallets:
    """The two wallet daemons and the funder's own address."""

    merchant: Rpc
    funder: Rpc
    funder_address: str


def wait_until(
    probe: Callable[[], Any],
    *,
    timeout: float,
    describe: str,
    interval: float = 0.5,
) -> Any:
    """Run `probe` until it returns something truthy, or say what it kept saying."""
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = probe()
        except JsonRpcError as exc:
            last = exc
        else:
            if last:
                return last
        time.sleep(interval)

    raise AssertionError(f"{describe} (last answer: {last!r})")


# ---------------------------------------------------------------------------
# Provisioning: the wallets real nodes need before anyone can pay
# ---------------------------------------------------------------------------


def fund_miner(node: BitcoinNode) -> BitcoinWallets:
    """A wallet with keys and spendable coins, which the test pays from."""
    node.call("createwallet", {"wallet_name": BTC_MINER_WALLET, "descriptors": True})

    # A *change* address, deliberately: the watch wallet imports only the
    # external descriptor, so coins mined to the internal chain can never be an
    # address an invoice is derived for. Mining to the first receive address
    # instead would make the app's first invoice an address that already has
    # 101 coinbase rewards on it - a test that settles for the wrong reason.
    mining_address = node.call(
        "getrawchangeaddress",
        {"address_type": "bech32"},
        wallet=BTC_MINER_WALLET,
    )
    # A hundred blocks is instant on Linux and not on Windows: writing them to
    # a laptop disk measured minutes there. The wait is generous on purpose -
    # the alternative is a burn-in that fails on a developer's machine for a
    # reason that has nothing to do with the app.
    node.call(
        "generatetoaddress",
        {"address": mining_address, "nblocks": MINED_BLOCKS},
        wallet=BTC_MINER_WALLET,
        timeout=BTC_MINING_TIMEOUT,
    )
    return BitcoinWallets(mining_address=mining_address)


def create_watch_wallet(node: BitcoinNode) -> None:
    """The wallet the app derives addresses from: public keys only.

    The import is the interesting part: the watch wallet gets the miner's
    *public* descriptor, ranged and marked active, which is what makes
    `getnewaddress` on a keyless wallet return addresses the node will scan
    for. That is exactly the setup a merchant runs with a hardware wallet, and
    exactly what a stub cannot verify.
    """
    listed = node.call("listdescriptors", wallet=BTC_MINER_WALLET)["descriptors"]
    receive = next(
        (
            descriptor
            for descriptor in listed
            if descriptor.get("active")
            and not descriptor.get("internal")
            and descriptor["desc"].startswith("wpkh(")
        ),
        None,
    )
    if receive is None:
        raise AssertionError(
            "the miner wallet has no active wpkh receive descriptor to import"
        )

    node.call(
        "createwallet",
        {
            "wallet_name": BTC_WATCH_WALLET,
            "disable_private_keys": True,
            "blank": True,
            "descriptors": True,
        },
    )
    imported = node.call(
        "importdescriptors",
        {
            "requests": [
                {
                    "desc": receive["desc"],
                    "active": True,
                    "internal": False,
                    # Two hundred is plenty for a burn-in's handful of invoices
                    # and fast to derive; a production import would be wider.
                    "range": [0, 200],
                    "timestamp": "now",
                    # No `label` here: bitcoind refuses one on a ranged
                    # descriptor (-8), and this import is ranged by design. The
                    # first real run found that; the stub had accepted it.
                }
            ]
        },
        wallet=BTC_WATCH_WALLET,
        timeout=DESCRIPTOR_IMPORT_TIMEOUT,
    )
    if not imported or not imported[0].get("success"):
        raise AssertionError(f"the watch wallet refused the descriptor: {imported}")

    # The app's docs claim it holds no spending key. The burn-in can check that
    # claim against the node it is talking to, rather than trusting the setup.
    info = node.call("getwalletinfo", wallet=BTC_WATCH_WALLET)
    if info.get("private_keys_enabled"):
        raise AssertionError("the watch wallet has private keys; it must not")


def provision_bitcoin(node: BitcoinNode) -> BitcoinWallets:
    """Both wallets: the funded miner, then the keyless copy the app uses."""
    wallets = fund_miner(node)
    create_watch_wallet(node)
    return wallets


def _open_or_create(wallet: Rpc, filename: str) -> None:
    """Create the wallet file, or open it if a previous run left it behind."""
    try:
        wallet.call(
            "create_wallet",
            {"filename": filename, "password": "", "language": "English"},
        )
        return
    except JsonRpcError as exc:
        message = str(exc).lower()
        if "already" not in message and "exists" not in message:
            raise

    try:
        wallet.call("open_wallet", {"filename": filename, "password": ""})
    except JsonRpcError as exc:
        # Already open under this name is the state we want; anything else is a
        # real problem and should be reported with the node's own words.
        if "already" not in str(exc).lower():
            raise


def provision_monero(daemon: Rpc, merchant: Rpc, funder: Rpc) -> MoneroWallets:
    """Two wallet files, and coins in the funder's from regtest blocks."""
    _open_or_create(merchant, XMR_MERCHANT_WALLET)
    _open_or_create(funder, XMR_FUNDER_WALLET)

    funder_address = funder.call("get_address", {"account_index": 0})["address"]
    daemon.call(
        "generateblocks",
        {
            "amount_of_blocks": MONERO_FUNDING_BLOCKS,
            "wallet_address": funder_address,
            "starting_nonce": 0,
        },
        timeout=MONERO_MINING_TIMEOUT,
    )

    funder.call("refresh")
    wait_until(
        lambda: funder.call("get_balance", {"account_index": 0}).get(
            "unlocked_balance", 0
        )
        > 0,
        timeout=120,
        describe="the funder's regtest coins never unlocked",
    )

    return MoneroWallets(merchant=merchant, funder=funder, funder_address=funder_address)


# ---------------------------------------------------------------------------
# Paying, the way a customer would
# ---------------------------------------------------------------------------


def pay_bitcoin(
    node: BitcoinNode, wallets: BitcoinWallets, address: str, amount: str
) -> str:
    """Send `amount` BTC from the miner and confirm it in one block."""
    txid = node.call(
        "sendtoaddress",
        # A float here is not a rounding risk worth inventing: bitcoind keeps
        # the decimal token it receives and parses it as fixed point, and every
        # amount this app asks for is eight places at most.
        {"address": address, "amount": float(Decimal(amount))},
        wallet=BTC_MINER_WALLET,
    )
    mine_bitcoin(node, wallets, blocks=1)
    return str(txid)


def mine_bitcoin(node: BitcoinNode, wallets: BitcoinWallets, *, blocks: int) -> None:
    node.call(
        "generatetoaddress",
        {"address": wallets.mining_address, "nblocks": blocks},
        wallet=BTC_MINER_WALLET,
        timeout=BTC_MINING_TIMEOUT,
    )


def pay_monero(
    daemon: Rpc,
    wallets: MoneroWallets,
    address: str,
    amount_atomic: int,
    *,
    blocks: int = 3,
) -> str:
    """Send piconero from the funder to the invoice's subaddress, then confirm."""
    tx = wallets.funder.call(
        "transfer",
        {
            "destinations": [{"address": address, "amount": int(amount_atomic)}],
            "account_index": 0,
            "priority": 0,
            "get_tx_key": True,
        },
    )
    mine_monero(daemon, wallets, blocks=blocks)
    return str(tx.get("tx_hash") or "")


def mine_monero(daemon: Rpc, wallets: MoneroWallets, *, blocks: int) -> None:
    daemon.call(
        "generateblocks",
        {
            "amount_of_blocks": blocks,
            "wallet_address": wallets.funder_address,
            "starting_nonce": 0,
        },
        timeout=MONERO_MINING_TIMEOUT,
    )


# ---------------------------------------------------------------------------
# The rate feed, and the API
# ---------------------------------------------------------------------------


class _RateHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - the name http.server calls
        encoded = json.dumps(RATES).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args):  # keep the test report readable
        pass


def start_rate_feed() -> ThreadingHTTPServer:
    """A local CoinGecko-shaped endpoint, so the quote has a price without one."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RateHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server


def skip_reason() -> Optional[str]:
    """Why this machine cannot run the burn-in, or None when it can."""
    if os.getenv("RUN_CRYPTO_BURNIN") != "1":
        return "crypto burn-in is opt-in: set RUN_CRYPTO_BURNIN=1"

    if shutil.which("docker") is None:
        return (
            "docker is not on PATH: the burn-in runs bitcoind, monerod and two "
            "wallet daemons in containers"
        )

    try:
        probe = subprocess.run(
            ["docker", "compose", "version"], capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"docker compose could not be run: {exc}"

    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip().splitlines()
        return "docker compose is not available: " + (
            detail[-1] if detail else f"exit {probe.returncode}"
        )

    if not COMPOSE_FILE.is_file():
        return f"the compose file is missing: {COMPOSE_FILE}"

    return None


class BurnIn:
    """One burn-in run: containers up, wallets provisioned, API up."""

    def __init__(self) -> None:
        # A fresh project name means fresh volumes: a chain left over from an
        # earlier run would make every assertion about a payment a guess.
        self.project = f"iftr-burnin-{uuid.uuid4().hex[:8]}"
        self.ports = {
            "btc": free_port(),
            "monerod": free_port(),
            "xmr_merchant": free_port(),
            "xmr_funder": free_port(),
            "api": free_port(),
        }
        self.log_dir = LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.compose_log = self.log_dir / f"{self.project}-compose.log"
        self.api_log = self.log_dir / f"{self.project}-api.log"
        self.database = self.log_dir / f"{self.project}.db"
        self.api_process: Optional[subprocess.Popen] = None
        self.rate_server: Optional[ThreadingHTTPServer] = None
        self.bitcoin: Optional[BitcoinNode] = None
        self.xmr_daemon: Optional[Rpc] = None
        self.monero: Optional[MoneroWallets] = None
        self.btc_wallets: Optional[BitcoinWallets] = None
        self.api_url = ""

    # -- containers ---------------------------------------------------------

    def _compose(self, args: List[str], *, timeout: float = 900.0) -> None:
        command = [
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            str(COMPOSE_FILE),
            *args,
        ]
        env = dict(os.environ)
        env.update(
            {
                "BURNIN_BTC_PORT": str(self.ports["btc"]),
                "BURNIN_MONEROD_PORT": str(self.ports["monerod"]),
                "BURNIN_XMR_MERCHANT_PORT": str(self.ports["xmr_merchant"]),
                "BURNIN_XMR_FUNDER_PORT": str(self.ports["xmr_funder"]),
                "BURNIN_BTC_USER": BTC_USER,
                "BURNIN_BTC_PASSWORD": BTC_PASSWORD,
                "BURNIN_MONERO_LOGIN": f"{MONERO_USER}:{MONERO_PASSWORD}",
            }
        )
        with self.compose_log.open("a", encoding="utf-8") as log:
            log.write(f"\n$ {' '.join(command)}\n")
            log.flush()
            completed = subprocess.run(
                command,
                cwd=str(BACKEND),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        if completed.returncode != 0:
            raise AssertionError(
                f"docker compose {' '.join(args)} failed with {completed.returncode}\n"
                f"--- {self.compose_log} ---\n{tail(self.compose_log, lines=60)}"
            )

    def start_containers(self) -> None:
        """Pull, start, and wait for both nodes and both wallet daemons."""
        self._compose(["up", "-d", "--remove-orphans"])

        self.bitcoin = BitcoinNode(f"http://127.0.0.1:{self.ports['btc']}")
        self.bitcoin.wait_ready()

        # The daemon is unauthenticated and the two wallet daemons are not: the
        # wallet images bind loopback unless a login is configured, and a
        # loopback bind inside a container cannot be published. The daemon only
        # serves this private network and 127.0.0.1, so it does not need one.
        self.xmr_daemon = Rpc(f"http://127.0.0.1:{self.ports['monerod']}/json_rpc")
        auth = {"user": MONERO_USER, "password": MONERO_PASSWORD}
        merchant = Rpc(
            f"http://127.0.0.1:{self.ports['xmr_merchant']}/json_rpc", **auth
        )
        funder = Rpc(f"http://127.0.0.1:{self.ports['xmr_funder']}/json_rpc", **auth)

        wait_until(
            lambda: self.xmr_daemon.call("get_info").get("status") == "OK",
            timeout=240,
            describe="monerod regtest never answered",
        )
        for name, wallet in (("merchant", merchant), ("funder", funder)):
            wait_until(
                lambda wallet=wallet: "version" in wallet.call("get_version"),
                timeout=120,
                describe=f"the {name} wallet-RPC never answered",
            )

        self.btc_wallets = provision_bitcoin(self.bitcoin)
        self.monero = provision_monero(self.xmr_daemon, merchant, funder)

    # -- the API ------------------------------------------------------------

    def _api_env(self) -> Dict[str, str]:
        """A clean environment, so a developer's own wallet URLs are not used."""
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("BITCOIN_", "MONERO_", "CRYPTO_", "STRIPE_"))
            and key not in {"DATABASE_URL", "UPLOADS_DIR", "UPLOADS_GC_LOG"}
        }
        assert self.rate_server is not None
        rate_url = f"http://127.0.0.1:{self.rate_server.server_address[1]}"
        env.update(
            {
                "DATABASE_URL": f"sqlite+aiosqlite:///{self.database.as_posix()}",
                "BITCOIN_RPC_URL": f"http://127.0.0.1:{self.ports['btc']}",
                "BITCOIN_WALLET": BTC_WATCH_WALLET,
                "BITCOIN_RPC_USER": BTC_USER,
                "BITCOIN_RPC_PASSWORD": BTC_PASSWORD,
                "MONERO_WALLET_RPC_URL": (
                    f"http://127.0.0.1:{self.ports['xmr_merchant']}/json_rpc"
                ),
                "MONERO_WALLET_RPC_USER": MONERO_USER,
                "MONERO_WALLET_RPC_PASSWORD": MONERO_PASSWORD,
                "CRYPTO_RATE_URL": rate_url,
                # One second, so the test waits for the watcher rather than for
                # a schedule; this is the only setting that exists for the test.
                "CRYPTO_WATCH_INTERVAL_SECONDS": "1",
                "CRYPTO_QUOTE_MINUTES": "15",
                "CRYPTO_BTC_CONFIRMATIONS": "1",
                "CRYPTO_XMR_CONFIRMATIONS": "2",
                "LOG_LEVEL": "INFO",
            }
        )
        return env

    def start_api(self) -> None:
        """The real app, with the real watcher, against the real wallets."""
        self.rate_server = start_rate_feed()
        self.api_url = f"http://127.0.0.1:{self.ports['api']}"
        self.api_process = spawn(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.ports["api"]),
                "--log-level",
                "info",
            ],
            cwd=BACKEND,
            env=self._api_env(),
            log=self.api_log,
        )
        wait_for(f"{self.api_url}/openapi.json", 180, self.api_process, self.api_log)

        # The watcher is what these tests are about; prove crypto is configured
        # before paying anything, so a boot problem cannot masquerade as a
        # payment problem later.
        methods = httpx.get(f"{self.api_url}/api/payments/methods", timeout=30).json()
        if not methods["crypto"]["enabled"]:
            raise AssertionError(
                "the API started without crypto configured: "
                f"{methods.get('crypto')} (see {self.api_log})"
            )

    # -- teardown -----------------------------------------------------------

    def dump_container_logs(self) -> None:
        """Keep what the containers said, for the run that failed."""
        try:
            with (self.log_dir / f"{self.project}-containers.log").open(
                "w", encoding="utf-8"
            ) as log:
                subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-p",
                        self.project,
                        "-f",
                        str(COMPOSE_FILE),
                        "logs",
                        "--no-color",
                        "--tail",
                        "4000",
                    ],
                    cwd=str(BACKEND),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=180,
                )
        except (OSError, subprocess.SubprocessError):
            pass

    def stop(self) -> None:
        if self.api_process is not None:
            stop(self.api_process)
            self.api_process = None
        if self.rate_server is not None:
            self.rate_server.shutdown()
            self.rate_server.server_close()
            self.rate_server = None

        try:
            # `-v` on purpose: the volumes hold a chain and two wallets, and the
            # next run must start from a clean regtest.
            self._compose(["down", "-v", "--remove-orphans"], timeout=300)
        except AssertionError:
            self.dump_container_logs()
            raise
