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
