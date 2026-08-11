from urllib.parse import parse_qs, urlparse

import pytest
import responses

from hoodgrow import (
    HOODGROW_TOOLS,
    HoodGrowClient,
    execute_hoodgrow_tool,
    hoodgrow_anthropic_tools,
    hoodgrow_openai_tools,
)

BASE = "https://www.hoodgrow.com"

EXPECTED_TOOLS = [
    "get_catalog",
    "get_token",
    "get_corporate_actions",
    "get_defi",
    "get_holders",
    "get_slippage",
    "get_ohlc",
    "get_base_tokens",
]

_CATALOG_BODY = {
    "chainId": 4663,
    "updatedAt": "2026-07-30T00:00:00.000Z",
    "tokens": [],
    "pendingCorporateActions": [],
    "recentCorporateActions": [],
}


def test_hoodgrow_tools_exposes_the_eight_read_tools_with_object_schemas():
    assert [t["name"] for t in HOODGROW_TOOLS] == EXPECTED_TOOLS
    for t in HOODGROW_TOOLS:
        assert t["parameters"]["type"] == "object"
        assert t["parameters"]["additionalProperties"] is False
        assert len(t["description"]) > 20
    slippage = next(t for t in HOODGROW_TOOLS if t["name"] == "get_slippage")
    assert slippage["parameters"]["required"] == ["symbol", "amountUsd", "side"]


def test_openai_and_anthropic_adapters_wrap_the_same_tools():
    openai = hoodgrow_openai_tools()
    assert len(openai) == len(EXPECTED_TOOLS)
    assert openai[0]["type"] == "function"
    assert openai[0]["function"]["name"] == "get_catalog"

    anthropic = hoodgrow_anthropic_tools()
    assert anthropic[1]["name"] == "get_token"
    assert anthropic[1]["input_schema"]["type"] == "object"
    assert "parameters" not in anthropic[1]  # Anthropic uses input_schema


@responses.activate
def test_execute_hoodgrow_tool_dispatches_to_the_right_endpoint():
    responses.add(responses.GET, f"{BASE}/api/agent/tokens", json=_CATALOG_BODY, status=200)
    responses.add(
        responses.GET,
        f"{BASE}/api/agent/slippage/NVDA",
        json={
            "chainId": 4663,
            "symbol": "NVDA",
            "side": "buy",
            "amountUsd": 10000,
            "updatedAt": "2026-08-08T00:00:00.000Z",
            "bestPoolAddress": None,
            "bestEffectivePrice": None,
            "pools": [],
            "note": "n",
        },
        status=200,
    )

    client = HoodGrowClient(api_key="k")
    execute_hoodgrow_tool(client, "get_catalog")
    execute_hoodgrow_tool(
        client, "get_slippage", {"symbol": "nvda", "amountUsd": 10000, "side": "buy"}
    )

    assert urlparse(responses.calls[0].request.url).path == "/api/agent/tokens"
    slip = urlparse(responses.calls[1].request.url)
    assert slip.path == "/api/agent/slippage/NVDA"
    q = parse_qs(slip.query)
    assert q["amountUsd"] == ["10000.0"]
    assert q["side"] == ["buy"]


@responses.activate
def test_execute_hoodgrow_tool_forwards_idempotency_key():
    responses.add(responses.GET, f"{BASE}/api/agent/tokens", json=_CATALOG_BODY, status=200)

    client = HoodGrowClient(api_key="k")
    execute_hoodgrow_tool(client, "get_catalog", idempotency_key="tool-1")

    assert responses.calls[0].request.headers.get("Idempotency-Key") == "tool-1"


def test_execute_hoodgrow_tool_rejects_unknown_tool():
    client = HoodGrowClient(api_key="k")
    with pytest.raises(ValueError, match="Unknown HoodGrow tool: get_moon_phase"):
        execute_hoodgrow_tool(client, "get_moon_phase")


def test_execute_hoodgrow_tool_rejects_missing_required_argument():
    client = HoodGrowClient(api_key="k")
    with pytest.raises(ValueError, match="must be a non-empty string"):
        execute_hoodgrow_tool(client, "get_token", {})
