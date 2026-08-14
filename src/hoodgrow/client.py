"""Client for the HoodGrow agent API (https://docs.hoodgrow.com)."""

from __future__ import annotations

import math
import time
from typing import Any, Iterator
from urllib.parse import quote

import requests

from ._version import __version__
from .models import (
    BaseTokensResponse,
    CatalogResponse,
    CorporateActionEvent,
    CorporateActionFeedStatus,
    CorporateActions,
    CorporateActionsFeedResponse,
    CreditBalance,
    CreditBundle,
    CreditPurchaseAck,
    CreditWebhookRegistration,
    DefiDetailResponse,
    HoldersResponse,
    MarketsResponse,
    OhlcInterval,
    OhlcResponse,
    PingResponse,
    SlippageResponse,
    SlippageSide,
    TokenDetailResponse,
    TradesResponse,
)

DEFAULT_BASE_URL = "https://www.hoodgrow.com"
#: Base mainnet, CAIP-2 form — the only network HoodGrow's x402 paywall accepts.
NETWORK = "eip155:8453"
#: Upper bound on any single 429 backoff wait, so a hostile/huge Retry-After
#: can't hang a caller indefinitely.
MAX_RETRY_DELAY_S = 30.0
#: Default per-request timeout. `requests` has NO timeout by default, so
#: without this a hung connection blocks the calling agent loop forever —
#: the exact failure mode an autonomous caller can't recover from.
DEFAULT_TIMEOUT_S = 30.0
#: USDC on Base has 6 decimals; x402 quotes amounts in atomic units.
USDC_DECIMALS = 6


def _usd_to_usdc_atomic(usd: float) -> int:
    """A USD ceiling as USDC atomic units, rounded UP.

    Rounding up on purpose: a ceiling of $0.10 must not reject a quote of
    exactly $0.10 because of binary floating point, and erring a hundredth
    of a cent high is harmless where erring low breaks legitimate calls."""
    return math.ceil(usd * 10**USDC_DECIMALS)


def _retry_after_seconds(header: str | None, attempt: int) -> float:
    """Delay before a 429 retry: honor ``Retry-After`` (seconds) when present
    and sane, else exponential backoff (0.5s, 1s, 2s, …), both capped."""
    if header:
        try:
            seconds = float(header)
        except ValueError:
            seconds = -1.0
        if seconds >= 0:
            return min(seconds, MAX_RETRY_DELAY_S)
    return min(0.5 * (2 ** (attempt - 1)), MAX_RETRY_DELAY_S)


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
        max_retries: int = 0,
        user_agent: str | None = None,
        timeout: float | None = DEFAULT_TIMEOUT_S,
        max_price_usd: float | None = None,
    ) -> None:
        """
        Args:
            api_key: Bearer API key, self-served at
                https://www.hoodgrow.com/profile — calls are free (no
                x402 payment) and unrate-limited beyond the key's own
                configured limit. Takes priority over ``signer`` if both
                are set.
            signer: An ``eth_account`` ``LocalAccount`` (e.g. from
                ``eth_account.Account.from_key``, or a KMS/HSM-backed
                custom account) used to auto-pay per call via x402 — USDC
                on Base, $0.10 for the full catalog, $0.05 for a single
                token. Every payment this client makes is real money;
                never hardcode a raw private key in source, load it from
                an environment variable or secret manager, and only fund
                the wallet with what you're willing to spend on this API.
            user_agent: Replace the ``User-Agent`` this client sends
                (default ``hoodgrow-py/<version>``). Set it when this SDK is
                embedded in something the API should count separately —
                otherwise that traffic is indistinguishable from a direct SDK
                integration. Convention is to keep the SDK visible behind your
                own name, e.g. ``my-app/2.1 (hoodgrow-py/0.11.0)``.
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
            max_retries: Auto-retry ``429 Too Many Requests`` this many
                times, honoring the response's ``Retry-After`` header
                (capped, with a small exponential fallback). Defaults to
                ``0`` (no retry). **Only applied on the bearer ``api_key``
                path**, where calls are free and safe to repeat — it is
                deliberately ignored for the ``signer`` (x402) and credit
                paths, because an x402 payment is not idempotent and a blind
                retry after a paid call can pay twice. There, a ``429``
                raises immediately.
            max_price_usd: Refuse to pay more than this many US dollars
                for any single call. Enforced as an x402 payment policy, so
                an over-priced 402 is rejected *before* the signer produces
                a signature — no payment is made and the call fails
                instead. Without it this client pays whatever a 402 quotes,
                which is fine against a known-good API and not fine if that
                API is ever misconfigured or impersonated. No default,
                deliberately: ``buy_credits`` legitimately pays $10–$200,
                so a ceiling sized for the $0.05–$0.10 read endpoints would
                silently break bundle purchases. It applies to credit
                purchases too — a read-only agent might set ``0.1``, while
                a client that also buys bundles needs it above the largest
                bundle. Ignored on the ``api_key`` path, where no payment
                happens at all.
            timeout: Per-request timeout in seconds, applied to every HTTP
                call this client makes (connect + read). Defaults to
                ``DEFAULT_TIMEOUT_S`` (30s). Pass ``None`` to disable and
                restore requests' wait-forever behavior — almost never what
                an agent loop wants, since a single hung connection then
                blocks it indefinitely. Note a timeout can fire AFTER the
                server started processing: on the paid paths, pair retries
                with ``idempotency_key`` so a timed-out call is safe to
                re-send without paying twice.
        """
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        # Identify the SDK on every request. Without it these calls arrive
        # with requests' generic User-Agent and land in the API's
        # unattributed bucket, indistinguishable from the crawlers and
        # liveness probes that sweep the public endpoints — which is exactly
        # the distinction its usage ledger exists to make. An integration
        # built on this SDK is the signal; a probe is the noise.
        self._session.headers["User-Agent"] = user_agent or f"hoodgrow-py/{__version__}"
        self._signer = signer
        self._use_credits = bool(use_credits and signer is not None and not api_key)
        self._using_api_key = bool(api_key)
        self._max_retries = max(0, int(max_retries))
        self._timeout = timeout

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
            if max_price_usd is not None:
                # x402's own max_amount policy, not a hand-rolled one: it
                # filters the 402's payment requirements before a signature
                # is produced, so an over-priced quote leaves nothing
                # acceptable to pay rather than being paid and regretted.
                from x402.client_base import max_amount

                x402_client.register_policy(max_amount(_usd_to_usdc_atomic(max_price_usd)))
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

    def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        # Retry a 429 ONLY on the free bearer path. x402/credit calls are not
        # idempotent (a retry can pay twice / re-spend), so they get one shot.
        max_attempts = self._max_retries + 1 if self._using_api_key else 1
        # Optional idempotency key — flows through on every path (the x402
        # payment adapter copies the original request's headers onto its paid
        # retry), so a caller can safely retry a timed-out paid call.
        extra_headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        attempt = 1
        while True:
            if self._use_credits:
                # A credit-spend call is NOT an x402 payment — it must bypass
                # self._session (wrapRequestsWithPayment patched it to handle
                # x402 challenges, which would misinterpret an "insufficient
                # credit balance" 402) and use a plain `requests.get` instead,
                # same as get_credit_balance/list_credit_bundles below.
                # Re-signed per attempt so a retry never replays a stale sig.
                headers = {**self._sign_credit_auth_headers("GET", path), **extra_headers}
                res = requests.get(
                    url, params=params, headers=headers, timeout=self._timeout
                )
            else:
                res = self._session.get(
                    url,
                    params=params,
                    headers=extra_headers or None,
                    timeout=self._timeout,
                )

            if res.ok:
                return res.json()

            if res.status_code == 429 and attempt < max_attempts:
                time.sleep(_retry_after_seconds(res.headers.get("Retry-After"), attempt))
                attempt += 1
                continue

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

    def ping(self, idempotency_key: str | None = None) -> PingResponse:
        """Prove the payment path works, for a tenth of a cent.

        Carries no market data — it exists so a new x402 integration can
        hit a real live 402, settle it, and get a 200 back before it risks
        a $0.10 catalog call on an untested wallet, signer or facilitator
        config. $0.001/call via x402, free with an API key.

        Make this the first call from any new setup. Every other method is
        the "then what" once this one returns ``ok=True``."""
        return PingResponse.model_validate(
            self._request("/api/agent/ping", idempotency_key=idempotency_key)
        )

    def get_catalog(self, idempotency_key: str | None = None) -> CatalogResponse:
        """The full token catalog — every listed Robinhood Chain stock
        token, with price, corporate-action adjusted supply, and DeFi
        depth. $0.10/call via x402, free with an API key.

        Pass ``idempotency_key`` (any unique, stable string) to safely retry
        a timed-out PAID call: the server replays the first stored response
        instead of charging again. Reuse a key only to retry the same call."""
        return CatalogResponse.model_validate(
            self._request("/api/agent/tokens", idempotency_key=idempotency_key)
        )

    def get_token(
        self, symbol: str, idempotency_key: str | None = None
    ) -> TokenDetailResponse:
        """One token by symbol, e.g. "NVDA" — same fields as a catalog
        entry, cheaper than fetching the whole catalog for a spot check.
        $0.05/call via x402, free with an API key. Raises
        :class:`HoodGrowError` (status 404) for an unknown symbol.
        ``idempotency_key`` makes a timed-out paid call safe to retry."""
        return TokenDetailResponse.model_validate(
            self._request(
                f"/api/agent/token/{quote(symbol.upper())}",
                idempotency_key=idempotency_key,
            )
        )

    def get_corporate_actions(
        self, symbol: str | None = None, idempotency_key: str | None = None
    ) -> CorporateActions:
        """Corporate actions (splits, dividends, name changes). Pass a
        symbol to scope to one token (uses the cheaper single-token
        endpoint); omit it for every tracked token's corporate actions
        (uses the full-catalog endpoint)."""
        data = (
            self.get_token(symbol, idempotency_key=idempotency_key)
            if symbol
            else self.get_catalog(idempotency_key=idempotency_key)
        )
        return CorporateActions(
            pending=data.pending_corporate_actions,
            recent=data.recent_corporate_actions,
        )

    def get_corporate_actions_feed(
        self,
        symbol: str | None = None,
        contract: str | None = None,
        status: CorporateActionFeedStatus | None = None,
        from_: str | None = None,
        to: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        idempotency_key: str | None = None,
    ) -> CorporateActionsFeedResponse:
        """One page of the filterable, cursor-paginated corporate-actions
        **event log** (``GET /api/corporate-actions``) — the cross-symbol
        append-only feed with detection metadata (block, tx hash,
        ``detected_at``), distinct from the pending/recent bundle
        :meth:`get_corporate_actions` returns for a single token. Filter by
        ``symbol``/``contract``/``status`` and an ISO ``from_``/``to`` range;
        page with ``pagination.next_cursor``, or use
        :meth:`iterate_corporate_actions` to walk every page automatically.
        $0.05/call via x402, free with an API key."""
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = symbol
        if contract is not None:
            params["contract"] = contract
        if status is not None:
            params["status"] = status
        if from_ is not None:
            params["from"] = from_
        if to is not None:
            params["to"] = to
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        return CorporateActionsFeedResponse.model_validate(
            self._request(
                "/api/corporate-actions",
                params=params or None,
                idempotency_key=idempotency_key,
            )
        )

    def iterate_corporate_actions(
        self,
        symbol: str | None = None,
        contract: str | None = None,
        status: CorporateActionFeedStatus | None = None,
        from_: str | None = None,
        to: str | None = None,
        limit: int | None = None,
    ) -> Iterator[CorporateActionEvent]:
        """Iterate over EVERY corporate-action event matching the filter,
        transparently following ``next_cursor`` across pages::

            for action in client.iterate_corporate_actions(status="staged"):
                ...

        Note each page is a separate billed request on the x402/credit
        paths, so a broad filter can fan out into many paid calls; narrow
        with ``from_``/``to``/``symbol``, or break out of the loop early."""
        cursor: str | None = None
        while True:
            page = self.get_corporate_actions_feed(
                symbol=symbol,
                contract=contract,
                status=status,
                from_=from_,
                to=to,
                limit=limit,
                cursor=cursor,
            )
            for action in page.actions:
                yield action
            cursor = page.pagination.next_cursor
            if not cursor:
                break

    def get_defi(
        self, symbol: str, idempotency_key: str | None = None
    ) -> DefiDetailResponse:
        """Every Morpho market this token participates in (loan OR
        collateral role) plus its Uniswap V3 pools — the full picture, not
        just the single best-APY figure bundled into ``get_catalog``/
        ``get_token``. $0.05/call via x402, free with an API key. Raises
        :class:`HoodGrowError` (status 404) for an unknown symbol."""
        return DefiDetailResponse.model_validate(
            self._request(
                f"/api/agent/defi/{quote(symbol.upper())}",
                idempotency_key=idempotency_key,
            )
        )

    def get_holders(
        self, symbol: str, limit: int | None = None, idempotency_key: str | None = None
    ) -> HoldersResponse:
        """Holder-count trend, 24h net total_supply change (real mint/burn
        — creation/redemption of the underlying tokenized shares, distinct
        from a corporate-action multiplier change), and top-holder
        concentration. ``limit`` caps how many top holders to return
        (1-50; the server defaults to 10 if omitted). $0.05/call via x402,
        free with an API key. Raises :class:`HoodGrowError` (status 404)
        for an unknown symbol."""
        params = {"limit": limit} if limit is not None else None
        return HoldersResponse.model_validate(
            self._request(
                f"/api/agent/holders/{quote(symbol.upper())}",
                params=params,
                idempotency_key=idempotency_key,
            )
        )

    def get_slippage(
        self,
        symbol: str,
        amount_usd: float,
        side: SlippageSide,
        idempotency_key: str | None = None,
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
                idempotency_key=idempotency_key,
            )
        )

    def get_ohlc(
        self,
        symbol: str,
        interval: OhlcInterval,
        from_: str | None = None,
        to: str | None = None,
        limit: int | None = None,
        idempotency_key: str | None = None,
    ) -> OhlcResponse:
        """OHLC price candles for backtesting, bucketed from ~15-min price
        snapshots. Each candle also carries per-candle ``volume_usd``/
        ``swap_count`` from the on-chain swap-log indexer (``None`` for
        buckets predating its deployment — see ``OhlcCandle``). ``from_``/
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
            self._request(
                f"/api/agent/ohlc/{quote(symbol.upper())}",
                params=params,
                idempotency_key=idempotency_key,
            )
        )

    def get_base_tokens(
        self, idempotency_key: str | None = None
    ) -> BaseTokensResponse:
        """Base mainnet (chain 8453) B20 native-equity-token registry — a
        much smaller sibling of :meth:`get_catalog`. PRE-LAUNCH: check
        each token's ``status`` before treating it as tradable —
        ``"pre_launch"`` means verified on-chain metadata but zero minted
        supply, so no price, no DEX liquidity, no holders exist for it
        yet; it flips to ``"live"`` automatically once real supply
        appears on-chain. $0.05/call via x402, free with an API key."""
        return BaseTokensResponse.model_validate(
            self._request("/api/agent/base/tokens", idempotency_key=idempotency_key)
        )

    def get_markets(
        self, limit: int | None = None, idempotency_key: str | None = None
    ) -> MarketsResponse:
        """Market movers across the whole Robinhood Chain catalog — top
        gainers and losers by 24h price change, highest 24h swap volume, and
        deepest Uniswap V3 liquidity (TVL). ``limit`` caps each list (1-50,
        default 10); gainers/losers can be empty when the market is flat.
        $0.05/call via x402, free with an API key."""
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        return MarketsResponse.model_validate(
            self._request(
                "/api/agent/markets",
                params=params,
                idempotency_key=idempotency_key,
            )
        )

    def get_trades(
        self,
        symbol: str | None = None,
        limit: int | None = None,
        idempotency_key: str | None = None,
    ) -> TradesResponse:
        """Recent large ("whale") trades in the stock-token Uniswap V3 pools,
        newest first — each with a buy/sell ``side``, USD size, and
        ``tx_hash``. Pass ``symbol`` to scope to one token (omit for the
        global feed); ``limit`` caps the list (1-100, default 20).
        $0.05/call via x402, free with an API key."""
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = symbol.upper()
        if limit is not None:
            params["limit"] = limit
        return TradesResponse.model_validate(
            self._request(
                "/api/agent/trades",
                params=params,
                idempotency_key=idempotency_key,
            )
        )

    def list_credit_bundles(self) -> dict[str, CreditBundle]:
        """Lists the current prepaid credit bundles (id -> {price_usd,
        credit_usd}) — no payment, no auth, works without a ``signer`` or
        ``api_key`` at all. See :meth:`buy_credits` to actually purchase
        one."""
        res = requests.get(
            f"{self._base_url}/api/agent/credits/purchase", timeout=self._timeout
        )
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
            timeout=self._timeout,
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
        res = requests.get(
            f"{self._base_url}{path}", headers=headers, timeout=self._timeout
        )
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

    def register_credit_webhook(
        self,
        url: str,
        symbols: list[str] | None = None,
    ) -> CreditWebhookRegistration:
        """Register (or update) a credit-funded corporate-action webhook for
        this wallet. HoodGrow then POSTs each matching ``corporate_action.*``
        event to ``url``, signed with the returned ``webhook_secret`` — verify
        every delivery with :func:`hoodgrow.verify_webhook_signature` before
        trusting it. Requires ``signer``.

        Registering is FREE (no credit spend here); each delivered event is
        billed per-event against this wallet's prepaid credit balance (see
        :meth:`buy_credits`/:meth:`get_credit_balance`), so an idle webhook
        that never fires costs nothing. A different ``url`` mints a fresh
        secret.

        ``symbols`` restricts delivery — and, since billing is per delivered
        event, what you're charged for — to just those symbols. Pass ``None``
        (or an empty list) to receive every token's events (the default).

        This is the credit-funded path only. A Builder-subscription webhook is
        set from the website (it uses wallet-session auth, not this SDK's
        ``signer``), so there's no SDK method for it."""
        if self._signer is None:
            raise ValueError("register_credit_webhook requires a `signer`")
        path = "/api/agent/credits/webhook"
        headers = {
            "Content-Type": "application/json",
            **self._sign_credit_auth_headers("POST", path),
        }
        payload: dict[str, Any] = {"webhookUrl": url}
        if symbols is not None:
            payload["webhookSymbols"] = symbols
        res = requests.post(
            f"{self._base_url}{path}",
            headers=headers,
            json=payload,
            timeout=self._timeout,
        )
        if not res.ok:
            body: Any = None
            try:
                body = res.json()
            except ValueError:
                pass
            raise HoodGrowError(
                f"failed to register credit webhook: {res.status_code} {res.reason}",
                res.status_code,
                body,
            )
        return CreditWebhookRegistration.model_validate(res.json())
