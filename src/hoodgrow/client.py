"""Client for the HoodGrow agent API (https://www.hoodgrow.com/api-access)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests

from .models import CatalogResponse, CorporateActions, TokenDetailResponse

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
                on Base, $0.50 for the full catalog, $0.05 for a single
                token. Every payment this client makes is real money;
                never hardcode a raw private key in source, load it from
                an environment variable or secret manager, and only fund
                the wallet with what you're willing to spend on this API.
            base_url: Override the API base URL — for testing against a
                non-production deployment. Defaults to
                https://www.hoodgrow.com.
        """
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()

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

    def _request(self, path: str) -> dict[str, Any]:
        res = self._session.get(f"{self._base_url}{path}")
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
        depth. $0.50/call via x402, free with an API key."""
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
