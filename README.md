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

## Quick start — prepaid credits (cheaper than x402 per call, still no signup)

Buy a dollar-denominated credit balance once via x402, then spend it down
over many calls with a cheap off-chain wallet signature instead of a fresh
on-chain payment every time:

```python
import os
from eth_account import Account
from hoodgrow import HoodGrowClient

signer = Account.from_key(os.environ["AGENT_PRIVATE_KEY"])

# One-time: pay via x402 for a bundle. Bundle ids/prices: client.list_credit_bundles().
paying_client = HoodGrowClient(signer=signer)
paying_client.buy_credits("50")  # pay $50, receive $60 of credit

# From then on: spend the balance instead of paying x402 per call.
client = HoodGrowClient(signer=signer, use_credits=True)
catalog = client.get_catalog()  # debits $0.10 from the balance, no on-chain tx

balance = client.get_credit_balance()  # free, doesn't spend anything
```

A credit spend is a different mechanism from x402 entirely — a short,
single-use, ~60-second-lived signed message, not an on-chain payment — so it
costs no gas and settles instantly. It only ever authenticates against
`www.hoodgrow.com`; nothing here signs a payment authorization.

## API

```python
HoodGrowClient(
    api_key: str | None = None,
    signer: LocalAccount | None = None,
    base_url: str = "https://www.hoodgrow.com",
    use_credits: bool = False,  # spend prepaid credit instead of x402 per call — requires signer + buy_credits() first
    max_retries: int = 0,       # auto-retry 429s (Retry-After aware). Bearer path only — never on x402/credit (would risk paying twice)
)
```

Exactly one of `api_key` / `signer` is required.

| Method | Price (x402) | Returns |
| --- | --- | --- |
| `get_catalog()` | $0.10 | Every listed token: price, source, 24h change, corporate-action adjusted supply, DeFi depth, plus catalog-wide pending/recent corporate actions |
| `get_token(symbol)` | $0.05 | One token, same fields, scoped |
| `get_corporate_actions(symbol=None)` | uses `get_token`/`get_catalog` above | `CorporateActions(pending=..., recent=...)` — pass a symbol to scope, omit for every tracked token |
| `get_corporate_actions_feed(symbol=None, contract=None, status=None, from_=None, to=None, limit=None, cursor=None)` | $0.05 | One page of the filterable, cursor-paginated corporate-actions **event log** — the cross-symbol append-only feed with detection metadata (block, tx hash, `detected_at`), distinct from the pending/recent bundle above |
| `iterate_corporate_actions(symbol=None, contract=None, status=None, from_=None, to=None, limit=None)` | $0.05 / page | Generator over **every** event matching the filter, auto-following `next_cursor` — `for a in client.iterate_corporate_actions(status="staged"): ...`. Each page is a separate billed call on x402/credit; narrow with `from_`/`to`/`symbol` |
| `get_defi(symbol)` | $0.05 | Every Morpho market this token participates in (loan OR collateral role) plus its Uniswap V3 pools — not just the single best-APY figure bundled into `get_catalog`/`get_token` |
| `get_holders(symbol, limit=None)` | $0.05 | Holder-count trend, 24h net supply change (real mint/burn), and top-holder concentration (`limit` caps how many holders to return, 1-50, defaults to 10 server-side) |
| `get_slippage(symbol, amount_usd, side)` | $0.05 | How much a USD-sized trade (`side: "buy" \| "sell"`) would move the price, per Uniswap V3 pool — `best_pool_address`/`best_effective_price` pick the best one for you |
| `get_ohlc(symbol, interval, from_=None, to=None, limit=None)` | $0.05 | OHLC price candles for backtesting (`interval: "1h" \| "4h" \| "1d"`; `from_`/`to` are ISO 8601 strings, default to the last 30 days). **OHLC only, no volume** — HoodGrow has no historical trading-volume time series to draw a volume field from |
| `get_base_tokens()` | $0.05 | Base mainnet (chain 8453) B20 native-equity-token registry — a much smaller sibling of `get_catalog`. **Pre-launch**: check each token's `status` (`"pre_launch" \| "live"`) before treating it as tradable — `"pre_launch"` means no price, no DEX liquidity, no holders exist for it yet |
| `list_credit_bundles()` | free | Current prepaid credit bundle catalog (`{id: CreditBundle(price_usd, credit_usd)}`) — no auth required |
| `buy_credits(bundle_id)` | one x402 payment | Pays for one bundle; requires `signer`. Balance lands once settlement confirms — see `get_credit_balance()` |
| `get_credit_balance()` | free | This wallet's current credit balance; requires `signer` |

Full response shapes are [Pydantic](https://docs.pydantic.dev) models
(`CatalogResponse`, `TokenDetailResponse`, `TokenSummary`, `DefiInfo`,
`PendingCorporateAction`, `RecentCorporateAction`, `DefiDetailResponse`,
`DefiMarket`, `DefiPool`, `HoldersResponse`, `TopHolder`, `SupplyChange24h`,
`SlippageResponse`, `SlippagePoolResult`, `OhlcResponse`, `OhlcCandle`,
`OhlcInterval`, `BaseTokensResponse`, `BaseToken`, `BaseTokenStatus`,
`CreditBundle`, `CreditPurchaseAck`, `CreditBalance`, `CorporateActionEvent`,
`CorporateActionsFeedResponse`, `WebhookEvent`) —
attributes are idiomatic `snake_case`; the API's own `camelCase` JSON keys
also work if you construct a model directly.

A failed request (any non-2xx HoodGrow itself returns, after x402 payment
handling — an unknown symbol, a server error) raises `HoodGrowError` with
`.status` and `.body`.

## Webhooks

Subscribe to corporate-action events instead of polling: register a webhook
(a Builder key's `webhookUrl`, or the credit-funded `POST
/api/agent/credits/webhook`) and HoodGrow POSTs each `corporate_action.*`
event to your URL, signed `x-hoodgrow-signature: sha256=<hex>`. **Verify that
signature before trusting the body** — this SDK ships the check so you don't
hand-roll the HMAC:

```python
from hoodgrow import verify_webhook_signature, WebhookEvent

# Flask — verify against the RAW body, not the parsed JSON (re-serializing breaks the digest):
@app.post("/hooks")
def hooks():
    if not verify_webhook_signature(
        request.get_data(), request.headers.get("x-hoodgrow-signature"), WEBHOOK_SECRET
    ):
        return "", 401
    event = WebhookEvent.model_validate_json(request.get_data())
    # event.event -> "corporate_action.staged" | "corporate_action.paused" | "corporate_action.applied" | "webhook.test"
    return "", 200
```

`verify_webhook_signature(raw_body, signature_header, secret)` is
constant-time, accepts the header with or without the `sha256=` prefix, and
returns `False` (never raises) for a missing header, malformed signature, or
any mismatch.

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

On the **bearer `api_key`** path (free, idempotent), pass `max_retries` to
have the client back off and retry `429`s for you, honoring `Retry-After`:

```python
client = HoodGrowClient(api_key=os.environ["HOODGROW_API_KEY"], max_retries=3)
```

`max_retries` is deliberately **ignored on the x402/credit paths** — those
calls aren't idempotent, so the client never auto-retries a paid request.
Need more sustained throughput? A persistent API key with its own higher
limit is available — see
[hoodgrow.com/api-access](https://www.hoodgrow.com/api-access).

## Idempotent retries (paid calls)

To retry a **paid** call that timed out without risking a double charge, pass
a stable `idempotency_key` — the server replays the first stored response
instead of charging again. Works on every metered read method (the x402
payment adapter preserves the header on its paid retry):

```python
import uuid

key = str(uuid.uuid4())  # one stable key per logical call
try:
    catalog = client.get_catalog(idempotency_key=key)
except Exception:
    # Timed out / network blip? Retrying with the SAME key is safe — a settled
    # first attempt is replayed, not re-charged.
    catalog = client.get_catalog(idempotency_key=key)
```

`idempotency_key` is a keyword argument on `get_catalog`, `get_token`,
`get_defi`, `get_holders`, `get_slippage`, `get_ohlc`, `get_base_tokens`, and
`get_corporate_actions_feed` (e.g. `get_holders("NVDA", 10, idempotency_key=key)`).
Reuse a key only to retry the exact same call — a key reused for a *different*
request is rejected with `422`.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest   # mocked HTTP via `responses`, no network dependency
```

## License

MIT
