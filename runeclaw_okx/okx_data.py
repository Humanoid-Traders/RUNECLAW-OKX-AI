"""
OKX public market-data adapter for RUNECLAW → OKX AI (Opportunity C).

Lets RUNECLAW's *stateless* analysis run on **OKX** markets (not just Bitget):
fetch OKX's public candles, feed them into RUNECLAW's pure analysis functions
(``run_quant_analysis`` / the backtest engine), and return only the **derived**
result.

**Data-redistribution guard (important).** OKX's API terms forbid reselling or
redistributing OKX market data verbatim — even from free endpoints. These tools
therefore return RUNECLAW's *derived* analysis (a quant report, backtest metrics)
and **never** the raw OKX candles. Keep it that way: don't add a tool that echoes
fetched candles back to the caller.

No API key is required — this uses OKX's public CEX market-data endpoint. RUNECLAW
is imported lazily inside the skill handlers, so this module imports without the
submodule (the OKX-tool invariant is testable on its own).
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

OKX_API_BASE = os.environ.get("OKX_API_BASE", "https://www.okx.com")
_CANDLES_PATH = "/api/v5/market/candles"
# OKX's /market/candles endpoint returns at most 300 rows per request.
_MAX_LIMIT = 300

_DERIVED_NOTE = (
    "Derived RUNECLAW analysis computed from OKX public market data; "
    "raw OKX market data is not redistributed."
)


class OKXDataError(RuntimeError):
    """Raised when OKX returns an error or an unparseable market-data response."""


def to_okx_inst_id(symbol: str) -> str:
    """'BTC/USDT' (or 'BTC/USDT:USDT') → OKX instId 'BTC-USDT'."""
    inst = symbol.strip().upper().replace("/", "-")
    return inst.split(":", 1)[0]  # drop any ccxt settle suffix → spot instrument


def to_okx_bar(timeframe: str) -> str:
    """RUNECLAW timeframe → OKX bar size.

    OKX uses lowercase 'm' for minutes and uppercase H/D/W/M for the larger units
    ('4h' → '4H', '1d' → '1D'); minutes stay lowercase ('15m' → '15m').
    """
    tf = timeframe.strip()
    if not tf:
        return "4H"
    num, unit = tf[:-1], tf[-1]
    if unit in ("h", "H"):
        return f"{num}H"
    if unit in ("d", "D"):
        return f"{num}D"
    if unit in ("w", "W"):
        return f"{num}W"
    if unit == "m":
        return f"{num}m"
    return tf


async def _get_candles_payload(symbol: str, timeframe: str, limit: int) -> dict[str, Any]:
    """Fetch the raw OKX candles JSON payload (separated out for testability)."""
    params = {
        "instId": to_okx_inst_id(symbol),
        "bar": to_okx_bar(timeframe),
        "limit": str(limit),
    }
    async with httpx.AsyncClient(timeout=20.0, trust_env=True) as client:
        resp = await client.get(OKX_API_BASE + _CANDLES_PATH, params=params)
        resp.raise_for_status()
        return resp.json()


async def fetch_okx_candles(
    symbol: str, timeframe: str = "4h", limit: int = _MAX_LIMIT
) -> list[list[float]]:
    """Return OKX candles as ccxt-style ascending ``[[ts, o, h, l, c, v], ...]``."""
    limit = max(1, min(int(limit), _MAX_LIMIT))
    payload = await _get_candles_payload(symbol, timeframe, limit)
    if str(payload.get("code")) != "0":
        raise OKXDataError(
            f"OKX API error {payload.get('code')}: {payload.get('msg') or 'unknown'}"
        )
    rows = payload.get("data") or []
    # OKX rows are [ts, o, h, l, c, vol, ...] newest-first; take OHLCV, reverse.
    candles = [[float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in rows]
    candles.reverse()
    return candles


# ---------------------------------------------------------------------------
# OKX-data-fed analysis tools (read-only; derived output only)
# ---------------------------------------------------------------------------

class OKXQuantSkill:
    """Run RUNECLAW's quant report on OKX market data. Duck-typed skill."""

    name = "okx_quant"

    async def execute(self, engine: Any, **kwargs: Any) -> str:
        symbol = kwargs.get("symbol", "BTC/USDT")
        timeframe = kwargs.get("timeframe", "4h")
        limit = kwargs.get("limit", _MAX_LIMIT)
        ohlcv = await fetch_okx_candles(symbol, timeframe, limit)

        from bot.skills.quant_skill import run_quant_analysis

        report = run_quant_analysis(symbol, timeframe, ohlcv)
        return json.dumps(
            {"source": "okx-public-market-data", "_note": _DERIVED_NOTE, "report": report.to_dict()},
            default=str,
        )


class OKXBacktestSkill:
    """Run RUNECLAW's rule-based backtest on OKX market data. Duck-typed skill."""

    name = "okx_backtest"

    # Derived metrics surfaced from BacktestResult (never raw candles).
    _METRICS = (
        "symbol", "timeframe", "total_return_pct", "net_pnl", "total_trades",
        "win_rate", "profit_factor", "sharpe_ratio", "sortino_ratio",
        "calmar_ratio", "max_drawdown_pct", "max_consecutive_losses",
    )

    async def execute(self, engine: Any, **kwargs: Any) -> str:
        symbol = kwargs.get("symbol", "BTC/USDT")
        timeframe = kwargs.get("timeframe", "1h")
        limit = kwargs.get("limit", _MAX_LIMIT)
        raw = await fetch_okx_candles(symbol, timeframe, limit)

        from bot.backtest.data_loader import DataLoader
        from bot.backtest.engine import BacktestEngine
        from bot.backtest.models import BacktestConfig

        bars = DataLoader.from_ohlcv_list(raw, symbol=symbol)
        result = await BacktestEngine(BacktestConfig(symbol=symbol, timeframe=timeframe)).run(bars)
        dump = result.model_dump()
        summary = {k: dump.get(k) for k in self._METRICS if k in dump}
        return json.dumps(
            {"source": "okx-public-market-data", "_note": _DERIVED_NOTE, "backtest": summary},
            default=str,
        )


# Pure-data tool catalogue (mirrors MCPToolDef/MCPToolParam shape).
OKX_DATA_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "mcp_name": "runeclaw_okx_quant",
        "skill_name": "okx_quant",
        "description": (
            "Run RUNECLAW's quant report (market regime, GARCH volatility forecast, "
            "Hurst exponent, multi-factor edge-gate) on OKX public market data for a "
            "symbol. Returns derived analysis only — not raw OKX candles. Read-only."
        ),
        "params": (
            {
                "name": "symbol",
                "type": "string",
                "description": "Trading pair, e.g. 'BTC/USDT' (mapped to OKX 'BTC-USDT').",
                "required": True,
            },
            {
                "name": "timeframe",
                "type": "string",
                "description": "Candle timeframe, e.g. '1H', '4H', '1D'.",
                "required": False,
                "default": "4h",
            },
            {
                "name": "limit",
                "type": "integer",
                "description": "Number of candles to fetch (1-300).",
                "required": False,
                "default": _MAX_LIMIT,
            },
        ),
    },
    {
        "mcp_name": "runeclaw_okx_backtest",
        "skill_name": "okx_backtest",
        "description": (
            "Run RUNECLAW's rule-based strategy backtest on OKX public market data "
            "for a symbol; returns derived performance metrics (return, win rate, "
            "Sharpe/Sortino/Calmar, drawdown). Not raw OKX candles. Read-only."
        ),
        "params": (
            {
                "name": "symbol",
                "type": "string",
                "description": "Trading pair, e.g. 'BTC/USDT'.",
                "required": True,
            },
            {
                "name": "timeframe",
                "type": "string",
                "description": "Candle timeframe, e.g. '1H', '4H'.",
                "required": False,
                "default": "1h",
            },
            {
                "name": "limit",
                "type": "integer",
                "description": "Number of candles to backtest (1-300).",
                "required": False,
                "default": _MAX_LIMIT,
            },
        ),
    },
)

OKX_SKILL_NAMES: frozenset[str] = frozenset({"okx_quant", "okx_backtest"})


def okx_skill_instances() -> list[Any]:
    """Duck-typed skill objects to register so the server can dispatch OKX tools."""
    return [OKXQuantSkill(), OKXBacktestSkill()]


def assert_okx_readonly() -> None:
    """Fail closed if an OKX-data tool looks executable or maps off the allow-list."""
    seen: set[str] = set()
    for tool in OKX_DATA_TOOLS:
        name = tool["mcp_name"]
        if name in seen:
            raise RuntimeError(f"Duplicate OKX tool name: {name}")
        seen.add(name)
        if "execute" in name.lower():
            raise RuntimeError(f"OKX tool name looks executable: {name}")
        if tool["skill_name"] not in OKX_SKILL_NAMES:
            raise RuntimeError(
                f"OKX tool '{name}' maps to unknown skill '{tool['skill_name']}'"
            )
