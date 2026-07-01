"""
OKX DEX (Web3) market-data adapter for RUNECLAW → OKX AI (Opportunity C, DEX leg).

Extends the OKX data adapter to **on-chain / DEX** markets: fetch OKX's DEX market
candles for a token (any supported chain) and run RUNECLAW's stateless quant
analysis on them, returning only the **derived** result.

Unlike the public CEX endpoint, the DEX/Web3 API is authenticated — it needs an OKX
Developer-Portal **API key + secret + passphrase** (and a project id), supplied via
environment variables. This module is **fail-closed**: without credentials the tool
returns a clear error and never silently degrades.

**Data-redistribution guard:** as with the CEX leg, the tool returns RUNECLAW's
*derived* quant report, never the raw OKX DEX candles — and it deliberately does
**not** re-serve OKX's own smart-money / signal feeds (that would be redistribution).

> Live verification note: the request-signing scheme below is OKX's standard
> v5/Web3 HMAC-SHA256 scheme, unit-tested deterministically. The exact candles
> endpoint path is env-overridable (`OKX_DEX_API_BASE` / `OKX_DEX_CANDLES_PATH`) in
> case your OKX DEX API tier uses a different version — verify once with a real key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

OKX_DEX_API_BASE = os.environ.get("OKX_DEX_API_BASE", "https://web3.okx.com")
OKX_DEX_CANDLES_PATH = os.environ.get("OKX_DEX_CANDLES_PATH", "/api/v5/dex/market/candles")
_MAX_LIMIT = 300

_DERIVED_NOTE = (
    "Derived RUNECLAW analysis computed from OKX DEX market data; raw OKX market "
    "data and OKX signal feeds are not redistributed."
)


class OKXDexAuthError(RuntimeError):
    """Raised when OKX DEX API credentials are missing/incomplete."""


class OKXDexError(RuntimeError):
    """Raised when the OKX DEX API returns an error or unparseable response."""


def _iso_timestamp() -> str:
    """OKX timestamp: ISO-8601 UTC with milliseconds, e.g. 2020-12-08T09:08:57.715Z."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_credentials() -> dict[str, str]:
    """Read OKX DEX credentials from the environment (fail-closed)."""
    key = os.environ.get("OKX_API_KEY", "").strip()
    secret = os.environ.get("OKX_SECRET_KEY", "").strip()
    passphrase = os.environ.get("OKX_PASSPHRASE", "").strip()
    project = os.environ.get("OKX_PROJECT", "").strip()  # required for Web3/DEX
    missing = [
        n for n, v in (("OKX_API_KEY", key), ("OKX_SECRET_KEY", secret), ("OKX_PASSPHRASE", passphrase))
        if not v
    ]
    if missing:
        raise OKXDexAuthError(
            "OKX DEX credentials missing: " + ", ".join(missing) + ". "
            "Set OKX_API_KEY / OKX_SECRET_KEY / OKX_PASSPHRASE (and OKX_PROJECT) "
            "from your OKX Developer Portal."
        )
    return {"key": key, "secret": secret, "passphrase": passphrase, "project": project}


def sign(secret: str, timestamp: str, method: str, request_path: str, body: str = "") -> str:
    """OKX signature: base64(HMAC-SHA256(secret, timestamp + METHOD + requestPath + body))."""
    prehash = f"{timestamp}{method.upper()}{request_path}{body}".encode()
    digest = hmac.new(secret.encode(), prehash, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def build_headers(creds: dict[str, str], timestamp: str, method: str, request_path: str, body: str = "") -> dict[str, str]:
    headers = {
        "OK-ACCESS-KEY": creds["key"],
        "OK-ACCESS-SIGN": sign(creds["secret"], timestamp, method, request_path, body),
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": creds["passphrase"],
        "Content-Type": "application/json",
    }
    if creds.get("project"):
        headers["OK-ACCESS-PROJECT"] = creds["project"]
    return headers


async def _dex_get_payload(request_path: str, creds: dict[str, str], timestamp: str) -> dict[str, Any]:
    """GET a signed DEX endpoint (request_path includes the query string)."""
    headers = build_headers(creds, timestamp, "GET", request_path)
    async with httpx.AsyncClient(timeout=20.0, trust_env=True) as client:
        resp = await client.get(OKX_DEX_API_BASE + request_path, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def fetch_dex_candles(
    chain_index: str,
    token_address: str,
    bar: str = "4h",
    limit: int = _MAX_LIMIT,
    *,
    timestamp: str | None = None,
    creds: dict[str, str] | None = None,
) -> list[list[float]]:
    """Return OKX DEX candles as ccxt-style ascending ``[[ts, o, h, l, c, v], ...]``.

    ``timestamp`` / ``creds`` are injectable for testing; in production they default
    to the current time and the env credentials.
    """
    limit = max(1, min(int(limit), _MAX_LIMIT))
    creds = creds or load_credentials()
    timestamp = timestamp or _iso_timestamp()
    # Build the query ourselves so the signed path matches the sent path exactly.
    query = urlencode(
        {
            "chainIndex": str(chain_index),
            "tokenContractAddress": token_address,
            "bar": _to_okx_bar(bar),
            "limit": str(limit),
        }
    )
    request_path = f"{OKX_DEX_CANDLES_PATH}?{query}"
    payload = await _dex_get_payload(request_path, creds, timestamp)
    if str(payload.get("code")) != "0":
        raise OKXDexError(
            f"OKX DEX API error {payload.get('code')}: {payload.get('msg') or 'unknown'}"
        )
    rows = payload.get("data") or []
    candles = [[float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in rows]
    candles.reverse()  # OKX returns newest-first
    return candles


def _to_okx_bar(timeframe: str) -> str:
    """RUNECLAW timeframe → OKX bar size (mirrors the CEX adapter)."""
    tf = (timeframe or "4h").strip()
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


class OKXDexQuantSkill:
    """Run RUNECLAW's quant report on OKX DEX market data. Duck-typed skill."""

    name = "okx_dex_quant"

    async def execute(self, engine: Any, **kwargs: Any) -> str:
        chain = str(kwargs.get("chain", "")).strip()
        token = str(kwargs.get("token", "")).strip()
        timeframe = kwargs.get("timeframe", "4h")
        limit = kwargs.get("limit", _MAX_LIMIT)
        if not chain or not token:
            return json.dumps({"status": "error", "result": "chain and token are required"})

        ohlcv = await fetch_dex_candles(chain, token, timeframe, limit)
        label = f"DEX:{chain}:{token}"

        from bot.skills.quant_skill import run_quant_analysis

        report = run_quant_analysis(label, timeframe, ohlcv)
        return json.dumps(
            {
                "source": "okx-dex-market-data",
                "chain": chain,
                "token": token,
                "_note": _DERIVED_NOTE,
                "report": report.to_dict(),
            },
            default=str,
        )


DEX_DATA_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "mcp_name": "runeclaw_dex_quant",
        "skill_name": "okx_dex_quant",
        "description": (
            "Run RUNECLAW's quant report (regime, GARCH volatility, Hurst, edge-gate) "
            "on OKX DEX market data for an on-chain token. Returns derived analysis "
            "only — not raw OKX candles. Requires OKX DEX API credentials. Read-only."
        ),
        "params": (
            {
                "name": "chain",
                "type": "string",
                "description": "OKX chainIndex, e.g. '1' (Ethereum), '501' (Solana).",
                "required": True,
            },
            {
                "name": "token",
                "type": "string",
                "description": "Token contract address on that chain.",
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
)

DEX_SKILL_NAMES: frozenset[str] = frozenset({"okx_dex_quant"})


def okx_dex_skill_instances() -> list[Any]:
    return [OKXDexQuantSkill()]


def assert_dex_readonly() -> None:
    """Fail closed if a DEX tool looks executable or maps off the allow-list."""
    for tool in DEX_DATA_TOOLS:
        name = tool["mcp_name"]
        if "execute" in name.lower():
            raise RuntimeError(f"DEX tool name looks executable: {name}")
        if tool["skill_name"] not in DEX_SKILL_NAMES:
            raise RuntimeError(f"DEX tool '{name}' maps to unknown skill '{tool['skill_name']}'")
