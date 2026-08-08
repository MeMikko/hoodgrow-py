import pytest
import responses

from hoodgrow import HoodGrowClient, HoodGrowError

BASE = "https://www.hoodgrow.com"


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
                }
            ],
            "note": "OHLC only — no volume field; HoodGrow has no historical trading-volume time series.",
        },
        status=200,
    )

    client = HoodGrowClient(api_key="test-key-123")
    result = client.get_ohlc(
        "nvda", "1d", from_="2026-07-01T00:00:00.000Z", to="2026-08-01T00:00:00.000Z", limit=30
    )

    assert len(result.candles) == 1
    assert result.candles[0].sample_count == 96
    assert responses.calls[0].request.url == (
        f"{BASE}/api/agent/ohlc/NVDA?interval=1d&from=2026-07-01T00%3A00%3A00.000Z"
        "&to=2026-08-01T00%3A00%3A00.000Z&limit=30"
    )
