"""Response models for the HoodGrow agent API
(https://www.hoodgrow.com/api-access). Mirrors the server's own response
shapes exactly — see HoodGrow/src/app/api/agent/{tokens,token/[symbol]}/route.ts.

Every model accepts the API's own camelCase JSON keys directly (via
`populate_by_name`/aliases) while exposing idiomatic snake_case attributes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PriceSource = Literal["chainlink", "legacy"] | None


class _HoodGrowModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class DefiInfo(_HoodGrowModel):
    """Best current Morpho supply APY + Uniswap V3 depth for one token."""

    #: Percent, e.g. 4.82 for 4.82%. ``None`` (not ``0``) when the token
    #: isn't a loan asset in any known Morpho market — distinct from a
    #: real 0% APY.
    morpho_best_supply_apy: float | None = Field(None, alias="morphoBestSupplyApy")
    morpho_best_supply_apy_market_id: str | None = Field(
        None, alias="morphoBestSupplyApyMarketId"
    )
    #: Total USD TVL across every Uniswap V3 pool involving this token.
    #: ``None`` (not ``0``) when there's no pool at all.
    uniswap_tvl_usd: float | None = Field(None, alias="uniswapTvlUsd")
    uniswap_pool_count: int = Field(0, alias="uniswapPoolCount")


class TokenSummary(_HoodGrowModel):
    """One token's price/supply data, as it appears in a catalog response."""

    symbol: str
    name: str
    #: On-chain contract address on Robinhood Chain (chain id 4663).
    address: str
    price_usd: float | None = Field(None, alias="priceUsd")
    price_source: PriceSource = Field(None, alias="priceSource")
    change_24h_percent: float | None = Field(None, alias="change24hPercent")
    #: Corporate-action adjusted supply when available, else raw totalSupply.
    supply: float | None = None
    #: True when ``supply`` reflects the ERC-8056 uiMultiplier adjustment.
    supply_adjusted: bool = Field(False, alias="supplyAdjusted")
    snapshot_ts: str | None = Field(None, alias="snapshotTs")
    defi: DefiInfo


class PendingCorporateAction(_HoodGrowModel):
    """A staged, not-yet-effective on-chain multiplier change — rare; only
    large, price-discontinuity actions (a split) require it. Dividends do
    NOT appear here — see :class:`RecentCorporateAction`."""

    symbol: str
    name: str
    current_multiplier: float = Field(alias="currentMultiplier")
    staged_multiplier: float = Field(alias="stagedMultiplier")
    #: Human-readable summary, e.g. "4-for-1 split".
    change: str
    effective_at: str = Field(alias="effectiveAt")
    checked_at: str = Field(alias="checkedAt")


class RecentCorporateAction(_HoodGrowModel):
    """One entry from Robinhood's own official corporate-action ledger —
    dividends, splits, name changes, and more. The near-continuous feed;
    prefer this over :class:`PendingCorporateAction` for routine activity
    like dividends."""

    symbol: str
    name: str
    type: str
    type_label: str = Field(alias="typeLabel")
    status: str
    status_label: str = Field(alias="statusLabel")
    #: YYYY-MM-DD.
    process_date: str = Field(alias="processDate")
    detail: str | None = None
    details: dict[str, dict[str, str]] | None = None
    #: Citable URL for this specific corporate action.
    url: str


class CatalogResponse(_HoodGrowModel):
    """``GET /api/agent/tokens`` — the full catalog."""

    chain_id: int = Field(alias="chainId")
    updated_at: str = Field(alias="updatedAt")
    tokens: list[TokenSummary]
    pending_corporate_actions: list[PendingCorporateAction] = Field(
        alias="pendingCorporateActions"
    )
    recent_corporate_actions: list[RecentCorporateAction] = Field(
        alias="recentCorporateActions"
    )


class TokenDetail(_HoodGrowModel):
    """The ``token`` object inside :class:`TokenDetailResponse` — same
    fields as :class:`TokenSummary` minus ``defi``, which sits alongside
    it instead (see :class:`TokenDetailResponse`)."""

    symbol: str
    name: str
    address: str
    price_usd: float | None = Field(None, alias="priceUsd")
    price_source: PriceSource = Field(None, alias="priceSource")
    change_24h_percent: float | None = Field(None, alias="change24hPercent")
    supply: float | None = None
    supply_adjusted: bool = Field(False, alias="supplyAdjusted")
    snapshot_ts: str | None = Field(None, alias="snapshotTs")


class TokenDetailResponse(_HoodGrowModel):
    """``GET /api/agent/token/{symbol}`` — one token. Note ``defi`` sits
    alongside ``token``, not nested inside it (unlike
    :class:`CatalogResponse`, where each catalog entry carries its own
    ``defi``) — this mirrors the live API exactly rather than normalizing
    the two shapes to match."""

    chain_id: int = Field(alias="chainId")
    updated_at: str = Field(alias="updatedAt")
    token: TokenDetail
    defi: DefiInfo
    pending_corporate_actions: list[PendingCorporateAction] = Field(
        alias="pendingCorporateActions"
    )
    recent_corporate_actions: list[RecentCorporateAction] = Field(
        alias="recentCorporateActions"
    )


class CorporateActions(_HoodGrowModel):
    """Return type of :meth:`hoodgrow.HoodGrowClient.get_corporate_actions`."""

    pending: list[PendingCorporateAction]
    recent: list[RecentCorporateAction]
