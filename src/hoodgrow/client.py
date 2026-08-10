"""Client for the HoodGrow agent API (https://www.hoodgrow.com/api-access)."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import requests

from .models import (
    BaseTokensResponse,
    CatalogResponse,
    CorporateActions,
    CreditBalance,
    CreditBundle,
    CreditPurchaseAck,
    DefiDetailResponse,
    HoldersResponse,
    OhlcInterval,
    OhlcResponse,
    SlippageResponse,
    SlippageSide,
    TokenDetailResponse,
)

DEFAULT_BASE_URL = "https://www.hoodgrow.com"
#: Base mainnet, CAIP-2 form — the only network HoodGrow's x402 paywall accepts.
NETWORK = "eip155:8453"


class HoodGrowError(Exception):
    """Raised for any non-2xx response other than a 402 x402 handles itself."""

    def __init__(self, message: str, status: int, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class HoodGrowClient:
    """Client for the HoodGrow agent API. Construct with either ``api_key``
    (free, issued access) or ``signer`` (x402 pay-per-call, no signup) —
    exactly one is required.
    """

    def __init__(
        self,
        api_key: str | None = None,
        signer: Any | None = None,
        base_url: str = DEFAULT_BASE_URL,
        use_credits: bool = False,
    ) -> None:
        """
        Args:
            api_key: Bearer API key issued from HoodGrow's /admin/api-keys —
                calls are free (no x402 payment) and unrate-limited beyond
                the key's own configured limit. Takes priority over
                ``signer`` if both are set.
            signer: An ``eth_account`` ``LocalAccount`` (e.g. from
                ``eth_account.Account.from_key``, or a KMS/HSM-backed
                custom account) used to auto-pay per call via x402 — USDC
                on Base, $0.10 for the full catalog, $0.05 for a single
                token. Every payment this client makes is real money;
                never hardcode a raw private key in source, load it from
                an environment variable or secret manager, and only fund
                the wallet with what you're willing to spend on this API.
            base_url: Override the API base URL — for testing against a
                non-production deployment. Defaults to
                https://www.hoodgrow.com.
            use_credits: When ``True`` and ``signer`` is set, every metered
                call is authenticated by spending from that wallet's
                prepaid credit balance (see ``buy_credits``) instead of a
                fresh x402 payment — a lightweight signed message, no gas,
                no facilitator round trip. Defaults to ``False``, so an
                existing ``signer``-only client keeps paying x402 per call
                exactly as before; only opt in once you've actually bought
                credits for this wallet (calling with an empty balance
                fails with a 402 :class:`HoodGrowError` instead of falling
                back to x402). Ignored when ``api_key`` is set.
        """
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._signer = signer
        self._use_credits = bool(use_credits and signer is not None and not api_key)

        if api_key:
            self._session.headers["Authorization"] = f"Bearer {api_key}"
        elif signer is not None:
            # Imported lazily so `import hoodgrow` alone doesn't pull in
            # x402's EVM extras unless payment is actually configured.
            from x402 import x402ClientSync
            from x402.http.clients import wrapRequestsWithPayment
            from x402.mechanisms.evm.exact import ExactEvmScheme

            x402_client = x402ClientSync()
            x402_client.register(NETWORK, ExactEvmScheme(signer))
            wrapRequestsWithPayment(self._session, x402_client)
        else:
            raise ValueError(
                "HoodGrowClient requires either `api_key` or `signer` — "
                "see https://github.com/MeMikko/hoodgrow-py#readme"
            )

    def _sign_credit_auth_headers(self, method: str, path: str) -> dict[str, str]:
        """Off-chain wallet-signature auth for a credit-funded call —
        mirrors the server's own buildCreditAuthMessage exactly (HoodGrow/
        src/lib/creditAuth.ts): method + pathname (no query string, no
        host) + a fresh unix-second timestamp, EIP-191 ``personal_sign``'d
        by ``signer``. Single-use server-side (replay is rejected) and only
        valid for ~60 seconds, so it's generated fresh per call, never
        cached."""
        if self._signer is None:
            raise ValueError("credit auth requires a `signer`")
        from eth_account.messages import encode_defunct

        pathname = path.split("?")[0]
        timestamp = str(int(time.time()))
        message = f"HoodGrow credit spend\nmethod: {method.upper()}\npath: {pathname}\ntimestamp: {timestamp}"
        signed = self._signer.sign_message(encode_defunct(text=message))
        signature = signed.signature.hex()
        if not signature.startswith("0x"):
            signature = f"0x{signature}"
        return {
            "X-HoodGrow-Credit-Wallet": self._signer.address,
            "X-HoodGrow-Credit-Timestamp": timestamp,
            "X-HoodGrow-Credit-Signature": signature,
        }

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._use_credits:
            # A credit-spend call is NOT an x402 payment — it must bypass
            # self._session (wrapRequestsWithPayment patched it to handle
            # x402 challenges, which would misinterpret an "insufficient
            # credit balance" 402) and use a plain `requests.get` instead,
            # same as get_credit_balance/list_credit_bundles below.
            headers = self._sign_credit_auth_headers("GET", path)
            res = requests.get(f"{self._base_url}{path}", params=params, headers=headers)
        else:
            res = self._session.get(f"{self._base_url}{path}", params=params)
        if not res.ok:
            body: Any = None
            try:
                body = res.json()
            except ValueError:
                pass  # non-JSON error body — status/message still tell the caller what happened
            raise HoodGrowError(
                f"HoodGrow API request failed: {res.status_code} {res.reason}",
                res.status_code,
                body,
            )
        return res.json()

    def get_catalog(self) -> CatalogResponse:
        """The full token catalog — every listed Robinhood Chain stock
        token, with price, corporate-action adjusted supply, and DeFi
        depth. $0.10/call via x402, free with an API key."""
        return CatalogResponse.model_validate(self._request("/api/agent/tokens"))

    def get_token(self, symbol: str) -> TokenDetailResponse:
        """One token by symbol, e.g. "NVDA" — same fields as a catalog
        entry, cheaper than fetching the whole catalog for a spot check.
        $0.05/call via x402, free with an API key. Raises
        :class:`HoodGrowError` (status 404) for an unknown symbol."""
        return TokenDetailResponse.model_validate(
            self._request(f"/api/agent/token/{quote(symbol.upper())}")
        )

    def get_corporate_actions(self, symbol: str | None = None) -> CorporateActions:
        """Corporate actions (splits, dividends, name changes). Pass a
        symbol to scope to one token (uses the cheaper single-token
        endpoint); omit it for every tracked token's corporate actions
        (uses the full-catalog endpoint)."""
        data = self.get_token(symbol) if symbol else self.get_catalog()
        return CorporateActions(
            pending=data.pending_corporate_actions,
            recent=data.recent_corporate_actions,
        )

    def get_defi(self, symbol: str) -> DefiDetailResponse:
        """Every Morpho market this token participates in (loan OR
        collateral role) plus its Uniswap V3 pools — the full picture, not
        just the single best-APY figure bundled into ``get_catalog``/
        ``get_token``. $0.05/call via x402, free with an API key. Raises
        :class:`HoodGrowError` (status 404) for an unknown symbol."""
        return DefiDetailResponse.model_validate(
            self._request(f"/api/agent/defi/{quote(symbol.upper())}")
        )

    def get_holders(self, symbol: str, limit: int | None = None) -> HoldersResponse:
        """Holder-count trend, 24h net total_supply change (real mint/burn
        — creation/redemption of the underlying tokenized shares, distinct
        from a corporate-action multiplier change), and top-holder
        concentration. ``limit`` caps how many top holders to return
        (1-50; the server defaults to 10 if omitted). $0.05/call via x402,
        free with an API key. Raises :class:`HoodGrowError` (status 404)
        for an unknown symbol."""
        params = {"limit": limit} if limit is not None else None
        return HoldersResponse.model_validate(
            self._request(f"/api/agent/holders/{quote(symbol.upper())}", params=params)
        )

    def get_slippage(
        self, symbol: str, amount_usd: float, side: SlippageSide
    ) -> SlippageResponse:
        """Price-impact / slippage estimate for a USD-sized trade, per
        Uniswap V3 pool this token trades on. ``side="buy"`` spends USDG
        for the stock token; ``"sell"`` spends the stock token for USDG.
        Per-pool, not an optimal multi-pool route/split — see the
        response's ``note``. $0.05/call via x402, free with an API key.
        Raises :class:`HoodGrowError` (status 404) for an unknown symbol.
        """
        return SlippageResponse.model_validate(
            self._request(
                f"/api/agent/slippage/{quote(symbol.upper())}",
                params={"amountUsd": amount_usd, "side": side},
            )
        )

    def get_ohlc(
        self,
        symbol: str,
        interval: OhlcInterval,
        from_: str | None = None,
        to: str | None = None,
        limit: int | None = None,
    ) -> OhlcResponse:
        """OHLC price candles for backtesting, bucketed from ~15-min price
        snapshots. Deliberately OHLC, not OHLCV — HoodGrow has no historical
        trading-volume time series to draw a volume field from. ``from_``/
        ``to`` are ISO 8601 timestamps (default: the last 30 days); ``limit``
        caps how many candles to return (server default 500, max 1000).
        $0.05/call via x402, free with an API key. Raises
        :class:`HoodGrowError` (status 404) for an unknown symbol."""
        params: dict[str, Any] = {"interval": interval}
        if from_ is not None:
            params["from"] = from_
        if to is not None:
            params["to"] = to
        if limit is not None:
            params["limit"] = limit
        return OhlcResponse.model_validate(
            self._request(f"/api/agent/ohlc/{quote(symbol.upper())}", params=params)
        )

    def get_base_tokens(self) -> BaseTokensResponse:
        """Base mainnet (chain 8453) B20 native-equity-token registry — a
        much smaller sibling of :meth:`get_catalog`. PRE-LAUNCH: check
        each token's ``status`` before treating it as tradable —
        ``"pre_launch"`` means verified on-chain metadata but zero minted
        supply, so no price, no DEX liquidity, no holders exist for it
        yet; it flips to ``"live"`` automatically once real supply
        appears on-chain. $0.05/call via x402, free with an API key."""
        return BaseTokensResponse.model_validate(self._request("/api/agent/base/tokens"))

    def list_credit_bundles(self) -> dict[str, CreditBundle]:
        """Lists the current prepaid credit bundles (id -> {price_usd,
        credit_usd}) — no payment, no auth, works without a ``signer`` or
        ``api_key`` at all. See :meth:`buy_credits` to actually purchase
        one."""
        res = requests.get(f"{self._base_url}/api/agent/credits/purchase")
        if not res.ok:
            raise HoodGrowError(
                f"failed to list credit bundles: {res.status_code} {res.reason}",
                res.status_code,
                None,
            )
        body = res.json()
        return {k: CreditBundle.model_validate(v) for k, v in body["bundles"].items()}

    def buy_credits(self, bundle_id: str) -> CreditPurchaseAck:
        """Pays for one prepaid credit bundle via x402 — requires
        ``signer`` (a bearer-key client is already free/unmetered, so
        buying credits makes no sense for it). The wallet's balance is
        credited server-side once settlement confirms, which normally
        completes before this call returns; call :meth:`get_credit_balance`
        to be sure. After this, construct (or reconstruct) the client with
        ``use_credits=True`` to start spending the balance instead of
        paying x402 per call."""
        if self._signer is None:
            raise ValueError("buy_credits requires a `signer` — credit bundles are paid via x402")
        res = self._session.post(
            f"{self._base_url}/api/agent/credits/purchase",
            params={"bundle": bundle_id},
        )
        if not res.ok:
            body: Any = None
            try:
                body = res.json()
            except ValueError:
                pass
            raise HoodGrowError(
                f"credit purchase failed: {res.status_code} {res.reason}",
                res.status_code,
                body,
            )
        return CreditPurchaseAck.model_validate(res.json())

    def get_credit_balance(self) -> CreditBalance:
        """This wallet's current prepaid credit balance — free (no x402
        charge, no credit spend), authenticated with the same
        wallet-signature scheme every credit-funded call uses. Requires
        ``signer``."""
        path = "/api/agent/credits/balance"
        headers = self._sign_credit_auth_headers("GET", path)
        res = requests.get(f"{self._base_url}{path}", headers=headers)
        if not res.ok:
            body: Any = None
            try:
                body = res.json()
            except ValueError:
                pass
            raise HoodGrowError(
                f"failed to fetch credit balance: {res.status_code} {res.reason}",
                res.status_code,
                body,
            )
        return CreditBalance.model_validate(res.json())
