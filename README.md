# hoodgrow

Python SDK for the [HoodGrow](https://www.hoodgrow.com) Robinhood Chain
stock token API — live price, corporate-action adjusted supply (ERC-8056,
correct through stock splits), Morpho/Uniswap DeFi depth, and corporate
actions (splits, dividends). Pay per call via **x402** (USDC on Base) — no
signup — or use a bearer API key if you have one.

```bash
pip install hoodgrow
```

## Quick start — x402 (pay per call, no signup)

```python
import os
from eth_account import Account
from hoodgrow import HoodGrowClient

# Never hardcode a real private key — load it from an env var / secret
# manager, and only fund this wallet with what you're willing to spend
# on this API.
signer = Account.from_key(os.environ["AGENT_PRIVATE_KEY"])

client = HoodGrowClient(signer=signer)

catalog = client.get_catalog()   # $0.10 — every token
nvda = client.get_token("NVDA")  # $0.05 — one token
```

Every call settles a real USDC payment on Base mainnet. See **Payment
safety** below before you point this at a funded wallet.

## Quick start — API key (free, issued access)

```python
import os
from hoodgrow import HoodGrowClient

client = HoodGrowClient(api_key=os.environ["HOODGROW_API_KEY"])

catalog = client.get_catalog()
```

Get a key from HoodGrow directly — see
[hoodgrow.com/api-access](https://www.hoodgrow.com/api-access).

## API

```python
HoodGrowClient(api_key: str | None = None, signer: LocalAccount | None = None, base_url: str = "https://www.hoodgrow.com")
```

Exactly one of `api_key` / `signer` is required.

| Method | Price (x402) | Returns |
| --- | --- | --- |
| `get_catalog()` | $0.10 | Every listed token: price, source, 24h change, corporate-action adjusted supply, DeFi depth, plus catalog-wide pending/recent corporate actions |
| `get_token(symbol)` | $0.05 | One token, same fields, scoped |
| `get_corporate_actions(symbol=None)` | uses `get_token`/`get_catalog` above | `CorporateActions(pending=..., recent=...)` — pass a symbol to scope, omit for every tracked token |
| `get_defi(symbol)` | $0.05 | Every Morpho market this token participates in (loan OR collateral role) plus its Uniswap V3 pools — not just the single best-APY figure bundled into `get_catalog`/`get_token` |
| `get_holders(symbol, limit=None)` | $0.05 | Holder-count trend, 24h net supply change (real mint/burn), and top-holder concentration (`limit` caps how many holders to return, 1-50, defaults to 10 server-side) |
| `get_slippage(symbol, amount_usd, side)` | $0.05 | How much a USD-sized trade (`side: "buy" \| "sell"`) would move the price, per Uniswap V3 pool — `best_pool_address`/`best_effective_price` pick the best one for you |
| `get_ohlc(symbol, interval, from_=None, to=None, limit=None)` | $0.05 | OHLC price candles for backtesting (`interval: "1h" \| "4h" \| "1d"`; `from_`/`to` are ISO 8601 strings, default to the last 30 days). **OHLC only, no volume** — HoodGrow has no historical trading-volume time series to draw a volume field from |
| `get_base_tokens()` | $0.05 | Base mainnet (chain 8453) B20 native-equity-token registry — a much smaller sibling of `get_catalog`. **Pre-launch**: check each token's `status` (`"pre_launch" \| "live"`) before treating it as tradable — `"pre_launch"` means no price, no DEX liquidity, no holders exist for it yet |

Full response shapes are [Pydantic](https://docs.pydantic.dev) models
(`CatalogResponse`, `TokenDetailResponse`, `TokenSummary`, `DefiInfo`,
`PendingCorporateAction`, `RecentCorporateAction`, `DefiDetailResponse`,
`DefiMarket`, `DefiPool`, `HoldersResponse`, `TopHolder`, `SupplyChange24h`,
`SlippageResponse`, `SlippagePoolResult`, `OhlcResponse`, `OhlcCandle`,
`OhlcInterval`, `BaseTokensResponse`, `BaseToken`, `BaseTokenStatus`) —
attributes are idiomatic `snake_case`; the API's own `camelCase` JSON keys
also work if you construct a model directly.

A failed request (any non-2xx HoodGrow itself returns, after x402 payment
handling — an unknown symbol, a server error) raises `HoodGrowError` with
`.status` and `.body`.

## Payment safety

x402 payments are real money and are **not** idempotent — retrying a timed-
out request can pay twice. Before pointing a signer at this client:

- Only fund the wallet with what you're willing to spend on this API.
- `signer` must be an `eth_account` `LocalAccount` (e.g.
  `Account.from_key(...)`) that can sign locally.
- HoodGrow's paywall only ever asks for USDC (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`)
  on Base mainnet (`eip155:8453`), paid to
  `0x8520B3693a2Cf3c2bEa3a505Af3A9c1b093954c7`, capped at $0.10/call — this
  client's underlying `x402` dependency handles the protocol-level
  verification, but you're responsible for how much you fund the signing
  wallet with.

## Rate limits

30 requests/minute per IP by default for pay-per-call use. A `429` means
back off — check the response's `Retry-After` header rather than retrying
immediately (a blind retry after a paid call risks a duplicate payment).
Need more sustained throughput? A persistent API key with its own higher
limit is available — see
[hoodgrow.com/api-access](https://www.hoodgrow.com/api-access).

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest   # mocked HTTP via `responses`, no network dependency
```

## License

MIT
