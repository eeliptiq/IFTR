"""
The two ways this app asks a wallet what arrived.

Both adapters speak JSON-RPC over HTTP and neither holds a key that can spend:

  * `BitcoinCoreWallet` talks to a Bitcoin Core **watch-only** wallet. The
    server is given a descriptor/xpub wallet, so it can derive a fresh address
    per invoice and read what was paid to it, and it cannot move a satoshi.
  * `MoneroWalletRpc` talks to `monero-wallet-rpc`, which does hold the view key
    (and, in the usual setup, the spend key). That process belongs on localhost,
    behind its own login, and is the one piece here whose compromise costs
    money - which is why it is a URL setting and not something this app embeds.

Amounts come back in whole coins (Bitcoin) or atomic units as strings (Monero),
and both are converted here with `Decimal`; nothing in this module creates a
float. A wallet that is unreachable raises `CryptoWalletError`, which the routes
turn into a `503` rather than into "you have not paid".

The request shapes are pinned by tests against a stub JSON-RPC server. They are
not a substitute for a real node: the integration is verified against a wallet
that has a memory, and the README says so.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List
from urllib.parse import quote

import httpx

from app.crypto import ASSET_BTC, ASSET_XMR, CryptoWalletError, WalletReading

# A wallet that takes longer than this to answer is not answering; the poller
# will try again rather than hold the request open.
REQUEST_TIMEOUT_SECONDS = 10.0


class _JsonRpcClient:
    """The HTTP part both wallets share: POST JSON, read JSON, or say why not."""

    def __init__(self, url: str, *, user: str = "", password: str = "") -> None:
        self.url = url.rstrip("/")
        self._auth = (user, password) if user or password else None

    async def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(self.url, json=payload, auth=self._auth)
        except httpx.HTTPError as exc:
            raise CryptoWalletError(f"the wallet could not be reached: {exc}") from exc

        if response.status_code == 401:
            raise CryptoWalletError("the wallet refused its login")
        if response.status_code >= 400:
            raise CryptoWalletError(
                f"the wallet answered HTTP {response.status_code}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise CryptoWalletError("the wallet answered with something else") from exc

        if not isinstance(body, dict):
            raise CryptoWalletError("the wallet answered with something else")
        return body


def _atomic(value: Any, atomic_units: int) -> int:
    """A whole-coin amount (bitcoind's answer) as integer atomic units."""
    try:
        return int((Decimal(str(value)) * atomic_units).to_integral_value())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CryptoWalletError(f"the wallet sent an amount we cannot read: {value!r}") from exc


def _already_atomic(value: Any) -> int:
    """An amount that is *already* atomic units, as monero-wallet-rpc sends.

    Multiplying these by the coin's atomic units a second time is the mistake
    this function exists to make impossible: Monero transfers come back as
    piconero, which is the unit the invoice is stored in.
    """
    try:
        amount = int(str(value).strip())
    except (ValueError, TypeError) as exc:
        raise CryptoWalletError(f"the wallet sent an amount we cannot read: {value!r}") from exc
    if amount < 0:
        raise CryptoWalletError(f"the wallet sent a negative amount: {value!r}")
    return amount


class BitcoinCoreWallet(_JsonRpcClient):
    """A Bitcoin Core watch-only wallet.

    `getnewaddress` derives the next address from the imported descriptor, which
    is why the server needs no private key: it can generate addresses to watch,
    not keys to spend. `getreceivedbyaddress` is asked twice - once at zero
    confirmations for "seen", once at the required depth for "settled" - because
    that pair is exactly what the invoice status distinguishes.
    """

    asset_code = ASSET_BTC

    def __init__(
        self,
        url: str,
        *,
        user: str = "",
        password: str = "",
        wallet: str = "",
    ) -> None:
        self._wallet = wallet.strip()
        endpoint = url.rstrip("/")
        if self._wallet:
            endpoint = f"{endpoint}/wallet/{quote(self._wallet, safe='')}"
        super().__init__(endpoint, user=user, password=password)

    async def _call(self, method: str, params: List[Any]) -> Any:
        body = await self._post(
            {"jsonrpc": "1.0", "id": "iftr", "method": method, "params": params}
        )
        if body.get("error"):
            error = body["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise CryptoWalletError(f"bitcoind refused {method}: {message}")
        if "result" not in body:
            raise CryptoWalletError(f"bitcoind answered {method} without a result")
        return body["result"]

    async def new_address(self, label: str) -> str:
        result = await self._call("getnewaddress", [label])
        if not isinstance(result, str) or not result.strip():
            raise CryptoWalletError("bitcoind returned no address")
        return result.strip()

    async def received(self, address: str, *, confirmations: int) -> WalletReading:
        seen = _atomic(
            await self._call("getreceivedbyaddress", [address, 0]),
            self._asset_atomic_units(),
        )

        if confirmations <= 0:
            # No depth asked for: what has arrived is, by this deployment's own
            # policy, settled.
            return WalletReading(
                received_atomic=seen, confirmed_atomic=seen, confirmations=0
            )

        settled = _atomic(
            await self._call("getreceivedbyaddress", [address, confirmations]),
            self._asset_atomic_units(),
        )
        return WalletReading(
            received_atomic=seen,
            confirmed_atomic=settled,
            # Bitcoin Core does not report per-address depth here, so this is a
            # floor rather than a count: either it reached the depth or it has
            # not, and the UI says "waiting" rather than inventing a number.
            confirmations=confirmations if settled else 0,
        )

    @staticmethod
    def _asset_atomic_units() -> int:
        from app.crypto import BTC

        return BTC.atomic_units


class MoneroWalletRpc(_JsonRpcClient):
    """A `monero-wallet-rpc` wallet, one subaddress per invoice.

    A subaddress is the Monero equivalent of a fresh Bitcoin address: money sent
    to it lands in the same wallet, and the transfer carries the index that says
    which invoice it belongs to. `get_transfers` is filtered by the address we
    asked for so a shared account cannot confuse two orders.
    """

    asset_code = ASSET_XMR

    async def _call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        body = await self._post(
            {"jsonrpc": "2.0", "id": "iftr", "method": method, "params": params}
        )
        if body.get("error"):
            error = body["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise CryptoWalletError(f"monero-wallet-rpc refused {method}: {message}")
        result = body.get("result")
        if not isinstance(result, dict):
            raise CryptoWalletError(f"monero-wallet-rpc answered {method} oddly")
        return result

    async def new_address(self, label: str) -> str:
        result = await self._call(
            "create_address", {"account_index": 0, "label": label}
        )
        address = str(result.get("address") or "").strip()
        if not address:
            raise CryptoWalletError("monero-wallet-rpc returned no address")
        return address

    async def received(self, address: str, *, confirmations: int) -> WalletReading:
        result = await self._call(
            "get_transfers", {"in": True, "account_index": 0}
        )
        transfers = result.get("in") or []
        if not isinstance(transfers, list):
            raise CryptoWalletError("monero-wallet-rpc sent transfers we cannot read")

        received = 0
        settled = 0
        deepest = 0
        deepest_txid = ""
        for transfer in transfers:
            if not isinstance(transfer, dict):
                continue
            if str(transfer.get("address") or "") != address:
                continue
            amount = _already_atomic(transfer.get("amount", 0))
            depth = int(transfer.get("confirmations") or 0)
            received += amount
            if depth >= max(confirmations, 0):
                settled += amount
            if depth >= deepest:
                deepest = depth
                deepest_txid = str(transfer.get("txid") or "")

        return WalletReading(
            received_atomic=received,
            confirmed_atomic=settled,
            confirmations=deepest,
            txid=deepest_txid,
        )
