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


DefiMarketRole = Literal["loan", "collateral"]


class DefiMarket(_HoodGrowModel):
    """One Morpho market a token participates in — as the loan asset OR as
    collateral (a token can appear in multiple markets in either role)."""

    market_id: str = Field(alias="marketId")
    role: DefiMarketRole
    #: The OTHER asset in this market. ``None`` if that side's symbol was
    #: never recorded server-side.
    counterpart_symbol: str | None = Field(None, alias="counterpartSymbol")
    #: Percent, e.g. 4.82 for 4.82%.
    supply_apy: float | None = Field(None, alias="supplyApy")
    borrow_apy: float | None = Field(None, alias="borrowApy")
    tvl_usd: float | None = Field(None, alias="tvlUsd")
    ts: str


class DefiPool(_HoodGrowModel):
    pool_address: str = Field(alias="poolAddress")
    tvl_usd: float | None = Field(None, alias="tvlUsd")
    volume_24h_usd: float | None = Field(None, alias="volume24hUsd")
    #: Pips, e.g. 3000 = 0.3%.
    fee_tier_bps: int | None = Field(None, alias="feeTierBps")
    ts: str


class DefiDetailResponse(_HoodGrowModel):
    """``GET /api/agent/defi/{symbol}`` — every Morpho market and Uniswap
    V3 pool a token participates in, not just the single best-APY figure
    bundled into :class:`CatalogResponse`/:class:`TokenDetailResponse`'s
    ``defi`` field."""

    chain_id: int = Field(alias="chainId")
    symbol: str
    updated_at: str = Field(alias="updatedAt")
    morpho_markets: list[DefiMarket] = Field(alias="morphoMarkets")
    uniswap_pools: list[DefiPool] = Field(alias="uniswapPools")


class TopHolder(_HoodGrowModel):
    address: str
    balance: float
    #: Share of total supply, 0-100. ``None`` if total supply isn't known.
    percent_of_supply: float | None = Field(None, alias="percentOfSupply")


class SupplyChange24h(_HoodGrowModel):
    """Net total_supply change over ~24h — a real mint/burn proxy
    (creation/redemption of the underlying tokenized shares), distinct
    from a corporate-action multiplier change."""

    supply_now: float = Field(alias="supplyNow")
    supply_ref: float = Field(alias="supplyRef")
    change_percent: float = Field(alias="changePercent")
    ref_ts: str = Field(alias="refTs")


class TopHolders(_HoodGrowModel):
    snapshot_ts: str | None = Field(None, alias="snapshotTs")
    total_holders: int = Field(alias="totalHolders")
    holders: list[TopHolder]


class HoldersResponse(_HoodGrowModel):
    """``GET /api/agent/holders/{symbol}`` — holder-count trend, 24h net
    supply change, and top-holder concentration."""

    chain_id: int = Field(alias="chainId")
    symbol: str
    updated_at: str = Field(alias="updatedAt")
    holder_count: int | None = Field(None, alias="holderCount")
    holder_count_delta: int | None = Field(None, alias="holderCountDelta")
    holder_count_delta_since_ts: str | None = Field(None, alias="holderCountDeltaSinceTs")
    holder_snapshot_ts: str | None = Field(None, alias="holderSnapshotTs")
    supply_change_24h: SupplyChange24h | None = Field(None, alias="supplyChange24h")
    top_holders: TopHolders = Field(alias="topHolders")


SlippageSide = Literal["buy", "sell"]


class SlippagePoolResult(_HoodGrowModel):
    """One pool's price-impact estimate, OR an error explaining why that
    pool couldn't be priced (``error`` set, all the numeric fields absent)
    — never both."""

    pool_address: str = Field(alias="poolAddress")
    fee_tier: int | None = Field(None, alias="feeTier")
    snapshot_ts: str = Field(alias="snapshotTs")
    error: str | None = None
    amount_out: float | None = Field(None, alias="amountOut")
    fee_amount_usd: float | None = Field(None, alias="feeAmountUsd")
    mid_price_before: float | None = Field(None, alias="midPriceBefore")
    mid_price_after: float | None = Field(None, alias="midPriceAfter")
    effective_price: float | None = Field(None, alias="effectivePrice")
    price_impact_percent: float | None = Field(None, alias="priceImpactPercent")
    #: ``None`` means "can't tell" (unrecognized fee tier); ``True`` means
    #: this pool's estimate likely UNDERSTATES real slippage for this
    #: trade size.
    likely_crosses_tick: bool | None = Field(None, alias="likelyCrossesTick")


class SlippageResponse(_HoodGrowModel):
    """``GET /api/agent/slippage/{symbol}`` — how much a USD-sized trade
    would move the price, per Uniswap V3 pool. Per-pool, not an optimal
    multi-pool route/split — see ``note``."""

    chain_id: int = Field(alias="chainId")
    symbol: str
    side: SlippageSide
    amount_usd: float = Field(alias="amountUsd")
    updated_at: str = Field(alias="updatedAt")
    #: The pool with the lowest priceImpactPercent among the ones that
    #: priced successfully. ``None`` if none did.
    best_pool_address: str | None = Field(None, alias="bestPoolAddress")
    best_effective_price: float | None = Field(None, alias="bestEffectivePrice")
    pools: list[SlippagePoolResult]
    note: str


OhlcInterval = Literal["1h", "4h", "1d"]


class OhlcCandle(_HoodGrowModel):
    bucket_start: str = Field(alias="bucketStart")
    bucket_end_exclusive: str = Field(alias="bucketEndExclusive")
    open: float
    high: float
    low: float
    close: float
    #: How many raw ~15-min price snapshots contributed to this candle — a
    #: low count (e.g. 1) means a thinner spread, not a data error.
    sample_count: int = Field(alias="sampleCount")


class OhlcResponse(_HoodGrowModel):
    """``GET /api/agent/ohlc/{symbol}`` — OHLC price candles for
    backtesting. Deliberately OHLC, not OHLCV: HoodGrow has no historical
    trading-volume time series to draw a volume field from, so none is
    included."""

    chain_id: int = Field(alias="chainId")
    symbol: str
    interval: OhlcInterval
    from_: str = Field(alias="from")
    to: str
    updated_at: str = Field(alias="updatedAt")
    candles: list[OhlcCandle]
    note: str


BaseTokenStatus = Literal["pre_launch", "live"]


class BaseToken(_HoodGrowModel):
    """One Base (chain 8453) B20 native-equity token. ``status`` flips
    from ``"pre_launch"`` to ``"live"`` automatically once real supply
    appears on-chain — a ``"pre_launch"`` entry is not tradable: no price,
    no DEX liquidity, no holders exist for it yet."""

    symbol: str
    name: str
    address: str
    decimals: int
    status: BaseTokenStatus
    total_supply_raw: str = Field(alias="totalSupplyRaw")
    total_supply: float = Field(alias="totalSupply")
    checked_at: str | None = Field(None, alias="checkedAt")


class BaseTokensResponse(_HoodGrowModel):
    """``GET /api/agent/base/tokens`` — Base mainnet B20 native-equity-
    token registry, a much smaller sibling of :class:`CatalogResponse`
    (Robinhood Chain). See ``note`` and each token's ``status`` before
    treating any entry as tradable."""

    chain_id: int = Field(alias="chainId")
    updated_at: str = Field(alias="updatedAt")
    note: str
    tokens: list[BaseToken]


class CreditBundle(_HoodGrowModel):
    """One prepaid credit bundle offer — pay ``price_usd`` once via x402,
    receive ``credit_usd`` of spendable balance (``credit_usd >=
    price_usd``; the difference is the bundle's bonus). See
    :meth:`hoodgrow.HoodGrowClient.list_credit_bundles`/``buy_credits``."""

    price_usd: float = Field(alias="priceUsd")
    credit_usd: float = Field(alias="creditUsd")


class CreditPurchaseAck(_HoodGrowModel):
    """``POST /api/agent/credits/purchase`` response — an acknowledgment,
    not a confirmed balance: the actual credit lands once x402 settlement
    confirms server-side (normally before this response arrives). See
    :meth:`hoodgrow.HoodGrowClient.get_credit_balance` to confirm."""

    ok: bool
    bundle: str
    price_usd: float = Field(alias="priceUsd")
    credit_usd: float = Field(alias="creditUsd")
    note: str


class CreditBalance(_HoodGrowModel):
    """``GET /api/agent/credits/balance`` response."""

    wallet_address: str = Field(alias="walletAddress")
    balance_usd: float = Field(alias="balanceUsd")
