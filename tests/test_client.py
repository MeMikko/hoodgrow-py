import hashlib
import hmac

import pytest
import responses
from eth_account import Account

from hoodgrow import HoodGrowClient, HoodGrowError, verify_webhook_signature

BASE = "https://www.hoodgrow.com"

# Well-known public test private key (Hardhat/Anvil default account #0) —
# never funded, safe to hardcode in a test file.
TEST_ACCOUNT = Account.from_key(
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
)


def test_constructor_requires_api_key_or_signer():
    with pytest.raises(ValueError, match="requires either"):
        HoodGrowClient()


@responses.activate
def test_get_catalog_sends_bearer_header_and_hits_bulk_endpoint():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/tokens",
        json={
            "chainId": 4663,
            "updatedAt": "2026-07-30T00:00:00.000Z",
            "tokens": [],
            "pendingCorporateActions": [],
            "recentCorporateActions": [],
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    result = client.get_catalog()

    assert result.chain_id == 4663
    assert responses.calls[0].request.headers["Authorization"] == "Bearer test-key-123"


@responses.activate
def test_get_token_upper_cases_the_symbol():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/token/NVDA",
        json={
            "chainId": 4663,
            "updatedAt": "2026-07-30T00:00:00.000Z",
            "token": {
                "symbol": "NVDA",
                "name": "NVIDIA xStock",
                "address": "0x0",
                "priceUsd": 1,
                "priceSource": "chainlink",
                "change24hPercent": 0,
                "supply": 1,
                "supplyAdjusted": False,
                "snapshotTs": None,
            },
            "defi": {
                "morphoBestSupplyApy": None,
                "morphoBestSupplyApyMarketId": None,
                "uniswapTvlUsd": None,
                "uniswapPoolCount": 0,
            },
            "pendingCorporateActions": [],
            "recentCorporateActions": [],
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    result = client.get_token("nvda")

    assert result.token.symbol == "NVDA"
    assert result.defi.morpho_best_supply_apy is None


@responses.activate
def test_get_corporate_actions_with_symbol_scopes_to_single_token_endpoint():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/token/GE",
        json={
            "chainId": 4663,
            "updatedAt": "2026-07-30T00:00:00.000Z",
            "token": {
                "symbol": "GE",
                "name": "General Electric",
                "address": "0x0",
                "priceUsd": 1,
                "priceSource": "chainlink",
                "change24hPercent": 0,
                "supply": 1,
                "supplyAdjusted": False,
                "snapshotTs": None,
            },
            "defi": {
                "morphoBestSupplyApy": None,
                "morphoBestSupplyApyMarketId": None,
                "uniswapTvlUsd": None,
                "uniswapPoolCount": 0,
            },
            "pendingCorporateActions": [],
            "recentCorporateActions": [
                {
                    "symbol": "GE",
                    "name": "General Electric",
                    "type": "CORPORATE_ACTION_TYPE_CASH_DIVIDEND",
                    "typeLabel": "Cash Dividend",
                    "status": "CORPORATE_ACTION_STATUS_IN_PROGRESS",
                    "statusLabel": "In Progress",
                    "processDate": "2026-07-27",
                    "detail": "$0.47 per share",
                    "details": None,
                    "url": "https://www.hoodgrow.com/corporate-actions/2026-07-27-ge-cash-dividend",
                }
            ],
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    actions = client.get_corporate_actions("GE")

    assert len(actions.recent) == 1
    assert actions.recent[0].detail == "$0.47 per share"


@responses.activate
def test_non_2xx_response_raises_hoodgrow_error_with_status_and_body():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/token/NOTREAL",
        json={"error": "Unknown symbol"},
        status=404,
    )

    client = HoodGrowClient(api_key="test-key-123")
    with pytest.raises(HoodGrowError) as exc_info:
        client.get_token("NOTREAL")

    assert exc_info.value.status == 404
    assert exc_info.value.body == {"error": "Unknown symbol"}


@responses.activate
def test_base_url_override_is_respected():
    responses.add(
        responses.GET,
        "http://localhost:3000/api/agent/tokens",
        json={
            "chainId": 4663,
            "updatedAt": "2026-07-30T00:00:00.000Z",
            "tokens": [],
            "pendingCorporateActions": [],
            "recentCorporateActions": [],
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123", base_url="http://localhost:3000/")
    client.get_catalog()

    assert responses.calls[0].request.url == "http://localhost:3000/api/agent/tokens"


@responses.activate
def test_get_defi_upper_cases_the_symbol_and_hits_the_defi_endpoint():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/defi/NVDA",
        json={
            "chainId": 4663,
            "symbol": "NVDA",
            "updatedAt": "2026-08-08T00:00:00.000Z",
            "morphoMarkets": [
                {
                    "marketId": "0xabc",
                    "role": "collateral",
                    "counterpartSymbol": "USDG",
                    "supplyApy": 0.0482,
                    "borrowApy": 0.061,
                    "tvlUsd": 1284000,
                    "ts": "2026-08-08T00:00:00.000Z",
                }
            ],
            "uniswapPools": [],
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    result = client.get_defi("nvda")

    assert len(result.morpho_markets) == 1
    assert result.morpho_markets[0].role == "collateral"


@responses.activate
def test_get_holders_omits_limit_when_not_passed_includes_when_passed():
    body = {
        "chainId": 4663,
        "symbol": "NVDA",
        "updatedAt": "2026-08-08T00:00:00.000Z",
        "holderCount": 1342,
        "holderCountDelta": 12,
        "holderCountDeltaSinceTs": "2026-08-07T00:00:00.000Z",
        "holderSnapshotTs": "2026-08-08T00:00:00.000Z",
        "supplyChange24h": None,
        "topHolders": {"snapshotTs": "2026-08-08T00:00:00.000Z", "totalHolders": 1342, "holders": []},
    }
    responses.add(responses.GET, f"{BASE}/api/agent/holders/NVDA", json=body, status=200)
    responses.add(responses.GET, f"{BASE}/api/agent/holders/NVDA", json=body, status=200)

    client = HoodGrowClient(api_key="test-key-123")
    result = client.get_holders("nvda")
    client.get_holders("nvda", limit=25)

    assert result.holder_count == 1342
    assert responses.calls[0].request.url == f"{BASE}/api/agent/holders/NVDA"
    assert responses.calls[1].request.url == f"{BASE}/api/agent/holders/NVDA?limit=25"


@responses.activate
def test_get_slippage_builds_the_query_string_with_amount_usd_and_side():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/slippage/NVDA",
        json={
            "chainId": 4663,
            "symbol": "NVDA",
            "side": "buy",
            "amountUsd": 10000,
            "updatedAt": "2026-08-08T00:00:00.000Z",
            "bestPoolAddress": "0xpool",
            "bestEffectivePrice": 185.68,
            "pools": [],
            "note": "Per-pool estimate, not an optimal multi-pool route/split.",
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    result = client.get_slippage("nvda", 10000, "buy")

    assert result.best_pool_address == "0xpool"
    assert responses.calls[0].request.url == (
        f"{BASE}/api/agent/slippage/NVDA?amountUsd=10000&side=buy"
    )


@responses.activate
def test_get_ohlc_sends_only_interval_when_from_to_limit_are_omitted():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/ohlc/NVDA",
        json={
            "chainId": 4663,
            "symbol": "NVDA",
            "interval": "1h",
            "from": "2026-07-09T00:00:00.000Z",
            "to": "2026-08-08T00:00:00.000Z",
            "updatedAt": "2026-08-08T00:00:00.000Z",
            "candles": [],
            "note": "OHLC only — no volume field; HoodGrow has no historical trading-volume time series.",
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    result = client.get_ohlc("nvda", "1h")

    assert result.interval == "1h"
    assert result.from_ == "2026-07-09T00:00:00.000Z"
    assert responses.calls[0].request.url == f"{BASE}/api/agent/ohlc/NVDA?interval=1h"


@responses.activate
def test_get_ohlc_passes_from_to_and_limit_through_as_query_params():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/ohlc/NVDA",
        json={
            "chainId": 4663,
            "symbol": "NVDA",
            "interval": "1d",
            "from": "2026-07-01T00:00:00.000Z",
            "to": "2026-08-01T00:00:00.000Z",
            "updatedAt": "2026-08-08T00:00:00.000Z",
            "candles": [
                {
                    "bucketStart": "2026-07-01T00:00:00.000Z",
                    "bucketEndExclusive": "2026-07-02T00:00:00.000Z",
                    "open": 180.1,
                    "high": 182.5,
                    "low": 179.0,
                    "close": 181.2,
                    "sampleCount": 96,
                    "volumeUsd": 412683.55,
                    "swapCount": 1840,
                },
                {
                    "bucketStart": "2026-07-02T00:00:00.000Z",
                    "bucketEndExclusive": "2026-07-03T00:00:00.000Z",
                    "open": 181.2,
                    "high": 183.0,
                    "low": 180.5,
                    "close": 182.7,
                    "sampleCount": 96,
                    "volumeUsd": None,
                    "swapCount": None,
                },
            ],
            "note": "Each candle's volumeUsd/swapCount is USD swap volume across the token's Uniswap V3 pools; null for buckets older than the volume indexer's backfill window.",
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    result = client.get_ohlc(
        "nvda", "1d", from_="2026-07-01T00:00:00.000Z", to="2026-08-01T00:00:00.000Z", limit=30
    )

    assert len(result.candles) == 2
    assert result.candles[0].sample_count == 96
    assert result.candles[0].volume_usd == 412683.55
    assert result.candles[0].swap_count == 1840
    assert result.candles[1].volume_usd is None
    assert result.candles[1].swap_count is None
    assert responses.calls[0].request.url == (
        f"{BASE}/api/agent/ohlc/NVDA?interval=1d&from=2026-07-01T00%3A00%3A00.000Z"
        "&to=2026-08-01T00%3A00%3A00.000Z&limit=30"
    )


@responses.activate
def test_get_base_tokens_hits_the_base_registry_endpoint():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/base/tokens",
        json={
            "chainId": 8453,
            "updatedAt": "2026-08-08T12:00:00.000Z",
            "note": "PRE-LAUNCH: ...",
            "tokens": [
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "address": "0xb200000000000000000000C2e324d24d7eEcd1fb",
                    "decimals": 8,
                    "status": "pre_launch",
                    "totalSupplyRaw": "0",
                    "totalSupply": 0,
                    "checkedAt": "2026-08-08T12:00:00.000Z",
                }
            ],
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    result = client.get_base_tokens()

    assert result.chain_id == 8453
    assert len(result.tokens) == 1
    assert result.tokens[0].status == "pre_launch"
    assert responses.calls[0].request.url == f"{BASE}/api/agent/base/tokens"


@responses.activate
def test_list_credit_bundles_fetches_the_catalog_with_no_auth():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/credits/purchase",
        json={"bundles": {"10": {"priceUsd": 10, "creditUsd": 11}}},
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    bundles = client.list_credit_bundles()

    assert bundles["10"].price_usd == 10
    assert bundles["10"].credit_usd == 11


def test_get_credit_balance_requires_a_signer():
    client = HoodGrowClient(api_key="test-key-123")
    with pytest.raises(ValueError, match="requires a `signer`"):
        client.get_credit_balance()


def test_buy_credits_requires_a_signer():
    client = HoodGrowClient(api_key="test-key-123")
    with pytest.raises(ValueError, match="requires a `signer`"):
        client.buy_credits("10")


@responses.activate
def test_get_credit_balance_signs_the_canonical_message_and_sends_credit_auth_headers():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/credits/balance",
        json={"walletAddress": TEST_ACCOUNT.address.lower(), "balanceUsd": 5.5},
        status=200,
    )

    client = HoodGrowClient(signer=TEST_ACCOUNT)
    balance = client.get_credit_balance()

    assert balance.balance_usd == 5.5
    req = responses.calls[0].request
    assert req.headers["X-HoodGrow-Credit-Wallet"] == TEST_ACCOUNT.address
    assert req.headers["X-HoodGrow-Credit-Signature"].startswith("0x")
    assert int(req.headers["X-HoodGrow-Credit-Timestamp"]) > 0


@responses.activate
def test_use_credits_attaches_signed_headers_to_a_metered_get():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/tokens",
        json={
            "chainId": 4663,
            "updatedAt": "2026-07-30T00:00:00.000Z",
            "tokens": [],
            "pendingCorporateActions": [],
            "recentCorporateActions": [],
        },
        status=200,
    )

    client = HoodGrowClient(signer=TEST_ACCOUNT, use_credits=True)
    client.get_catalog()

    req = responses.calls[0].request
    assert req.headers["X-HoodGrow-Credit-Wallet"] == TEST_ACCOUNT.address
    assert req.headers["X-HoodGrow-Credit-Signature"].startswith("0x")


# One feed event, spread into tests that only care about a couple fields.
FEED_EVENT = {
    "symbol": "TSLA",
    "contract": "0x322F0929c4625eD5bAd873c95208D54E1c003b2d",
    "type": "staged",
    "actionType": "split",
    "multiplierFrom": 1,
    "multiplierTo": 3,
    "executionDate": "2026-08-20T13:30:00.000Z",
    "detectedAt": "2026-08-11T09:14:22.000Z",
    "lastUpdated": "2026-08-11T09:14:22.000Z",
    "freshnessSeconds": 17265,
    "blockNumber": 8421337,
    "transactionHash": "0xdeadbeef",
    "source": "onchain",
}


@responses.activate
def test_get_corporate_actions_feed_builds_filters_and_hits_feed_endpoint():
    responses.add(
        responses.GET,
        f"{BASE}/api/corporate-actions",
        json={
            "chainId": 4663,
            "updatedAt": "2026-08-11T14:00:00.000Z",
            "actions": [FEED_EVENT],
            "pagination": {"nextCursor": None, "limit": 50},
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    page = client.get_corporate_actions_feed(
        status="staged", symbol="tsla", from_="2026-08-01T00:00:00.000Z", limit=50
    )

    assert len(page.actions) == 1
    assert page.actions[0].source == "onchain"
    assert page.actions[0].multiplier_to == 3
    assert page.pagination.next_cursor is None

    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert q["status"] == ["staged"]
    assert q["symbol"] == ["tsla"]
    assert q["from"] == ["2026-08-01T00:00:00.000Z"]
    assert q["limit"] == ["50"]


@responses.activate
def test_iterate_corporate_actions_walks_every_page():
    responses.add(
        responses.GET,
        f"{BASE}/api/corporate-actions",
        json={
            "chainId": 4663,
            "updatedAt": "x",
            "actions": [{**FEED_EVENT, "symbol": "A"}],
            "pagination": {"nextCursor": "cursor-1", "limit": 50},
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE}/api/corporate-actions",
        json={
            "chainId": 4663,
            "updatedAt": "x",
            "actions": [{**FEED_EVENT, "symbol": "B"}],
            "pagination": {"nextCursor": None, "limit": 50},
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    seen = [event.symbol for event in client.iterate_corporate_actions(status="staged")]

    assert seen == ["A", "B"]

    from urllib.parse import parse_qs, urlparse

    q0 = parse_qs(urlparse(responses.calls[0].request.url).query)
    q1 = parse_qs(urlparse(responses.calls[1].request.url).query)
    assert "cursor" not in q0  # first page: no cursor
    assert q1["cursor"] == ["cursor-1"]  # second page follows next_cursor


def test_verify_webhook_signature_accepts_valid_and_rejects_tampering():
    secret = "whsec_test_secret"
    body = (
        '{"id":"NVDA-newly-pending-x","event":"corporate_action.staged",'
        '"symbol":"NVDA","currentMultiplier":1,"stagedMultiplier":3,'
        '"effectiveAt":null,"ts":"2026-08-11T09:14:22.000Z"}'
    )
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    assert verify_webhook_signature(body, f"sha256={sig}", secret) is True
    assert verify_webhook_signature(body, sig, secret) is True  # sha256= prefix optional
    assert verify_webhook_signature(body.encode(), f"sha256={sig}", secret) is True  # bytes
    assert verify_webhook_signature(body + " ", f"sha256={sig}", secret) is False  # tampered
    assert verify_webhook_signature(body, f"sha256={sig}", "wrong-secret") is False
    assert verify_webhook_signature(body, None, secret) is False  # missing header
    assert verify_webhook_signature(body, "sha256=not-valid-hex", secret) is False


@responses.activate
def test_max_retries_retries_429_on_bearer_then_succeeds():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/tokens",
        json={"error": "Too many requests"},
        status=429,
        headers={"Retry-After": "0"},
    )
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/tokens",
        json={
            "chainId": 4663,
            "updatedAt": "2026-07-30T00:00:00.000Z",
            "tokens": [],
            "pendingCorporateActions": [],
            "recentCorporateActions": [],
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123", max_retries=2)
    catalog = client.get_catalog()

    assert catalog.chain_id == 4663
    assert len(responses.calls) == 2


@responses.activate
def test_429_is_not_retried_by_default():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/tokens",
        json={"error": "Too many requests"},
        status=429,
    )

    client = HoodGrowClient(api_key="test-key-123")
    with pytest.raises(HoodGrowError) as exc:
        client.get_catalog()

    assert exc.value.status == 429
    assert len(responses.calls) == 1


@responses.activate
def test_max_retries_ignored_on_signer_path():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/tokens",
        json={"error": "Too many requests"},
        status=429,
        headers={"Retry-After": "0"},
    )

    client = HoodGrowClient(signer=TEST_ACCOUNT, max_retries=5)
    with pytest.raises(HoodGrowError) as exc:
        client.get_catalog()

    assert exc.value.status == 429
    assert len(responses.calls) == 1  # exactly one attempt despite max_retries=5


_CATALOG_BODY = {
    "chainId": 4663,
    "updatedAt": "2026-07-30T00:00:00.000Z",
    "tokens": [],
    "pendingCorporateActions": [],
    "recentCorporateActions": [],
}


@responses.activate
def test_idempotency_key_is_sent_as_header():
    responses.add(responses.GET, f"{BASE}/api/agent/tokens", json=_CATALOG_BODY, status=200)

    client = HoodGrowClient(api_key="test-key-123")
    client.get_catalog(idempotency_key="abc-123")

    assert responses.calls[0].request.headers.get("Idempotency-Key") == "abc-123"


@responses.activate
def test_no_idempotency_header_when_omitted():
    responses.add(responses.GET, f"{BASE}/api/agent/tokens", json=_CATALOG_BODY, status=200)

    client = HoodGrowClient(api_key="test-key-123")
    client.get_catalog()

    assert responses.calls[0].request.headers.get("Idempotency-Key") is None


@responses.activate
def test_idempotency_key_on_trailing_param_methods():
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/holders/NVDA",
        json={
            "chainId": 4663,
            "symbol": "NVDA",
            "updatedAt": "2026-08-08T00:00:00.000Z",
            "holderCount": 1,
            "holderCountDelta": None,
            "holderCountDeltaSinceTs": None,
            "holderSnapshotTs": None,
            "supplyChange24h": None,
            "topHolders": {"snapshotTs": None, "totalHolders": 1, "holders": []},
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    client.get_holders("nvda", 10, idempotency_key="hold-1")

    req = responses.calls[0].request
    assert req.headers.get("Idempotency-Key") == "hold-1"
    assert "limit=10" in req.url
