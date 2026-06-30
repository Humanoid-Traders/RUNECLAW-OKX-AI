"""
Tests for the OKX DEX (Web3) market-data adapter (runeclaw_okx/okx_dex.py).

Signing, header construction, fail-closed credential loading, mapping, payload
parsing, and the tool invariant are pure (always run). The end-to-end dispatch test
needs the RUNECLAW submodule and mocks the network — no test needs a real key or
live OKX access.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import math

import pytest

from runeclaw_okx import okx_dex as dex

_HAS_RUNECLAW = importlib.util.find_spec("bot") is not None
_CREDS = {"key": "k", "secret": "shh", "passphrase": "p", "project": "proj"}
_TS = "2026-06-30T20:00:00.000Z"


def _synthetic_candles(n: int = 200) -> list[list[float]]:
    out: list[list[float]] = []
    px = 2.5
    for i in range(n):
        px *= 1 + 0.003 * math.sin(i / 6.0)
        out.append([float(i * 3_600_000), px, px * 1.02, px * 0.98, px, 5000.0 + i])
    return out


# ---------------------------------------------------------------------------
# Signing + headers + credentials (pure)
# ---------------------------------------------------------------------------

class TestSigning:
    def test_sign_matches_okx_scheme(self):
        path = "/api/v5/dex/market/candles?bar=4H"
        expected = base64.b64encode(
            hmac.new(b"shh", (_TS + "GET" + path).encode(), hashlib.sha256).digest()
        ).decode()
        assert dex.sign("shh", _TS, "GET", path) == expected

    def test_headers_include_all_okx_fields(self):
        h = dex.build_headers(_CREDS, _TS, "GET", "/p")
        assert {
            "OK-ACCESS-KEY", "OK-ACCESS-SIGN", "OK-ACCESS-TIMESTAMP",
            "OK-ACCESS-PASSPHRASE", "OK-ACCESS-PROJECT",
        } <= set(h)

    def test_project_header_omitted_when_unset(self):
        creds = {**_CREDS, "project": ""}
        assert "OK-ACCESS-PROJECT" not in dex.build_headers(creds, _TS, "GET", "/p")

    def test_load_credentials_fail_closed(self, monkeypatch):
        for v in ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE"):
            monkeypatch.delenv(v, raising=False)
        with pytest.raises(dex.OKXDexAuthError, match="OKX_API_KEY"):
            dex.load_credentials()

    def test_load_credentials_from_env(self, monkeypatch):
        monkeypatch.setenv("OKX_API_KEY", "k")
        monkeypatch.setenv("OKX_SECRET_KEY", "s")
        monkeypatch.setenv("OKX_PASSPHRASE", "p")
        monkeypatch.setenv("OKX_PROJECT", "pr")
        assert dex.load_credentials()["project"] == "pr"


# ---------------------------------------------------------------------------
# Candle fetch/parse (network mocked, no env needed)
# ---------------------------------------------------------------------------

class TestFetchDexCandles:
    def test_parses_newest_first_into_ascending(self, monkeypatch):
        import asyncio

        async def fake_payload(request_path, creds, timestamp):
            return {
                "code": "0",
                "data": [
                    ["3000", "3", "3.1", "2.9", "3.05", "9"],
                    ["2000", "2", "2.1", "1.9", "2.05", "8"],
                    ["1000", "1", "1.1", "0.9", "1.05", "7"],
                ],
            }

        monkeypatch.setattr(dex, "_dex_get_payload", fake_payload)
        candles = asyncio.run(
            dex.fetch_dex_candles("1", "0xabc", "4h", 3, timestamp=_TS, creds=_CREDS)
        )
        assert [c[0] for c in candles] == [1000.0, 2000.0, 3000.0]
        assert all(len(c) == 6 for c in candles)

    def test_error_code_raises(self, monkeypatch):
        import asyncio

        async def fake_payload(request_path, creds, timestamp):
            return {"code": "50011", "msg": "Invalid sign", "data": []}

        monkeypatch.setattr(dex, "_dex_get_payload", fake_payload)
        with pytest.raises(dex.OKXDexError, match="50011"):
            asyncio.run(dex.fetch_dex_candles("1", "0xabc", "4h", 3, timestamp=_TS, creds=_CREDS))


class TestDexCatalogueInvariant:
    def test_assert_dex_readonly_passes(self):
        dex.assert_dex_readonly()

    def test_names_prefixed_and_non_executable(self):
        for t in dex.DEX_DATA_TOOLS:
            assert t["mcp_name"].startswith("runeclaw_dex_")
            assert "execute" not in t["mcp_name"].lower()
            assert t["skill_name"] in dex.DEX_SKILL_NAMES


# ---------------------------------------------------------------------------
# Dispatch through the extended server (network mocked)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_RUNECLAW, reason="RUNECLAW submodule not importable")
class TestDexToolDispatch:
    def _server(self, monkeypatch, token="dex-token"):
        import bot.mcp.server as mcp_server

        async def fake_fetch(chain, token_addr, bar="4h", limit=300, **kw):
            return _synthetic_candles(200)

        monkeypatch.setattr(dex, "fetch_dex_candles", fake_fetch)
        monkeypatch.setattr(mcp_server, "_MCP_AUTH_TOKEN", token)
        from runeclaw_okx.extended_server import build_extended_server

        return build_extended_server(), token

    def test_dex_quant_returns_derived_envelope(self, monkeypatch):
        import asyncio

        srv, token = self._server(monkeypatch)
        r = asyncio.run(
            srv.call_tool(
                "runeclaw_dex_quant",
                {"chain": "1", "token": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"},
                auth_token=token,
            )
        )
        assert r["status"] == "success"
        payload = json.loads(r["result"])
        assert payload["source"] == "okx-dex-market-data"
        assert "candles" not in payload and "ohlcv" not in payload  # derived only

    def test_dex_quant_requires_chain_and_token(self, monkeypatch):
        import asyncio

        srv, token = self._server(monkeypatch)
        # `token` required by schema; in-process call returns a structured error.
        r = asyncio.run(srv.call_tool("runeclaw_dex_quant", {"chain": "1"}, auth_token=token))
        assert r["status"] == "error"

    def test_dex_quant_enforces_auth(self, monkeypatch):
        import asyncio

        srv, _ = self._server(monkeypatch)
        r = asyncio.run(
            srv.call_tool("runeclaw_dex_quant", {"chain": "1", "token": "0x"}, auth_token="wrong")
        )
        assert r["status"] == "error" and "Authentication" in r["result"]
