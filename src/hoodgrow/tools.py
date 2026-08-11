"""Framework-agnostic agent tools for HoodGrow.

Wire HoodGrow into any function-calling agent (OpenAI, Anthropic, LangChain,
CrewAI, …). Each entry in :data:`HOODGROW_TOOLS` is the same read-only tool the
``hoodgrow-mcp`` server exposes — a name, a natural-language description, and a
JSON Schema for its arguments — so an LLM can pick and call it.

Two ways to use these:
    * Pass :func:`hoodgrow_openai_tools` / :func:`hoodgrow_anthropic_tools`
      straight into the OpenAI / Anthropic SDKs, then dispatch tool calls
      through :func:`execute_hoodgrow_tool`.
    * Or read :data:`HOODGROW_TOOLS` directly and adapt to any other framework
      (see the README for LangChain / CrewAI snippets).

Zero extra dependencies — plain data plus a dispatcher over an existing
:class:`hoodgrow.HoodGrowClient`.
"""

from __future__ import annotations

from typing import Any

from .client import HoodGrowClient

_SYMBOL_PROP = {
    "type": "string",
    "description": 'Ticker symbol, e.g. "NVDA" (case-insensitive).',
}

#: The eight read-only HoodGrow tools, mirroring the ``hoodgrow-mcp`` server.
#: Prices shown are the x402 per-call cost (free with an API key).
HOODGROW_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_catalog",
        "description": (
            "Full catalog of Robinhood Chain stock tokens: live price, corporate-action "
            "adjusted supply, DeFi depth (best Morpho supply APY, Uniswap V3 TVL), and "
            "pending/recent corporate actions for every listed token. $0.10 via x402, free "
            "with an API key — prefer get_token for a single symbol."
        ),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_token",
        "description": (
            "One Robinhood Chain stock token by symbol (e.g. NVDA): live price, "
            "corporate-action adjusted supply, DeFi depth, and pending/recent corporate "
            "actions. Cheaper than get_catalog for a single spot check ($0.05 via x402, "
            "free with an API key). Fails for an unknown symbol."
        ),
        "parameters": {
            "type": "object",
            "properties": {"symbol": _SYMBOL_PROP},
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_corporate_actions",
        "description": (
            "Pending (on-chain staged) and recent (official Robinhood ledger) corporate "
            "actions — splits, dividends, name changes. Pass a symbol to scope to one token "
            "(cheaper); omit it for every tracked token's corporate actions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": 'Ticker symbol to scope to, e.g. "NVDA". Omit for all tokens.',
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_defi",
        "description": (
            "Every Morpho lending market (as loan asset OR collateral, both roles labeled) "
            "and Uniswap V3 pool involving one token — the full picture for comparing yield/"
            "borrow options, not just the single best-APY figure in get_catalog/get_token. "
            "$0.05 via x402, free with an API key. Fails for an unknown symbol."
        ),
        "parameters": {
            "type": "object",
            "properties": {"symbol": _SYMBOL_PROP},
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_holders",
        "description": (
            "Holder-count trend, 24h net total_supply change (real mint/burn — creation/"
            "redemption of the underlying tokenized shares, distinct from a corporate-action "
            "multiplier change), and top-holder concentration for one token. $0.05 via x402, "
            "free with an API key. Fails for an unknown symbol."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": _SYMBOL_PROP,
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "How many top holders to return, 1-50. Defaults to 10.",
                },
            },
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_slippage",
        "description": (
            "How much a USD-sized trade would move the price, per Uniswap V3 pool this token "
            "trades on — plus best_pool_address/best_effective_price picking the best of them. "
            "Per-pool estimate, not an optimal multi-pool route/split; a likely_crosses_tick "
            "flag means the trade may be large enough to understate real slippage (consider "
            "splitting into TWAP tranches). $0.05 via x402, free with an API key."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": _SYMBOL_PROP,
                "amountUsd": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "Trade size in USD.",
                },
                "side": {
                    "type": "string",
                    "enum": ["buy", "sell"],
                    "description": (
                        '"buy" spends USDG for the stock token, '
                        '"sell" spends the stock token for USDG.'
                    ),
                },
            },
            "required": ["symbol", "amountUsd", "side"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_ohlc",
        "description": (
            "OHLC price candles for backtesting, bucketed from ~15-min price history. OHLC "
            "only, no volume — HoodGrow has no historical trading-volume series. Defaults to "
            "the last 30 days if from/to are omitted; window capped at 730 days. $0.05 via "
            "x402, free with an API key. Fails for an unknown symbol."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": _SYMBOL_PROP,
                "interval": {
                    "type": "string",
                    "enum": ["1h", "4h", "1d"],
                    "description": "Candle bucket size.",
                },
                "from": {
                    "type": "string",
                    "description": "ISO 8601 start (default: 30 days before `to`).",
                },
                "to": {"type": "string", "description": "ISO 8601 end (default: now)."},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": "Max candles to return, 1-1000. Defaults to 500.",
                },
            },
            "required": ["symbol", "interval"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_base_tokens",
        "description": (
            "Base mainnet (chain 8453) B20 native-equity-token registry — verified on-chain "
            "metadata for a fixed set of known tokens plus a liveness signal. PRE-LAUNCH: "
            'every token currently has zero minted supply; status flips to "live" once real '
            "supply appears on-chain. Do not treat a pre_launch entry as tradable. $0.05 via "
            "x402, free with an API key."
        ),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

#: The tool names, in order.
HOODGROW_TOOL_NAMES: list[str] = [tool["name"] for tool in HOODGROW_TOOLS]


def _require_str(args: dict[str, Any], field: str) -> str:
    value = args.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f'HoodGrow tool arg "{field}" must be a non-empty string')
    return value


def execute_hoodgrow_tool(
    client: HoodGrowClient,
    name: str,
    args: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> Any:
    """Execute one HoodGrow tool by name against a client, returning the same
    (Pydantic) response the matching client method returns.

    Raises :class:`hoodgrow.HoodGrowError` for an API failure, or
    :class:`ValueError` for an unknown tool name / missing required argument.
    ``idempotency_key`` is forwarded to the underlying paid call.
    """
    args = args or {}
    if name == "get_catalog":
        return client.get_catalog(idempotency_key=idempotency_key)
    if name == "get_token":
        return client.get_token(_require_str(args, "symbol"), idempotency_key=idempotency_key)
    if name == "get_corporate_actions":
        symbol = args.get("symbol")
        return client.get_corporate_actions(
            symbol if symbol else None, idempotency_key=idempotency_key
        )
    if name == "get_defi":
        return client.get_defi(_require_str(args, "symbol"), idempotency_key=idempotency_key)
    if name == "get_holders":
        return client.get_holders(
            _require_str(args, "symbol"),
            args.get("limit"),
            idempotency_key=idempotency_key,
        )
    if name == "get_slippage":
        return client.get_slippage(
            _require_str(args, "symbol"),
            float(args["amountUsd"]),
            args["side"],
            idempotency_key=idempotency_key,
        )
    if name == "get_ohlc":
        return client.get_ohlc(
            _require_str(args, "symbol"),
            args["interval"],
            from_=args.get("from"),
            to=args.get("to"),
            limit=args.get("limit"),
            idempotency_key=idempotency_key,
        )
    if name == "get_base_tokens":
        return client.get_base_tokens(idempotency_key=idempotency_key)
    raise ValueError(f"Unknown HoodGrow tool: {name}")


def hoodgrow_openai_tools() -> list[dict[str, Any]]:
    """The tools in OpenAI Chat Completions / Responses ``tools`` format."""
    return [{"type": "function", "function": tool} for tool in HOODGROW_TOOLS]


def hoodgrow_anthropic_tools() -> list[dict[str, Any]]:
    """The tools in Anthropic Messages ``tools`` format (``input_schema``)."""
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["parameters"],
        }
        for tool in HOODGROW_TOOLS
    ]
