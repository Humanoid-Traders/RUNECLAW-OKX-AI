"""
Tests for the OKX public market-data adapter (runeclaw_okx/okx_data.py).

Mapping + catalogue-invariant + payload-parsing tests are pure (always run). The
end-to-end dispatch test needs the RUNECLAW submodule and mocks the network, so no
test ever depends on live OKX connectivity.
"""

from __future__ import annotations

import importlib.util
import json
import math

import pytest

from runeclaw_okx import okx_data

_HAS_RUNECLAW = importlib.util.find_spec("bot") is not None


def _synthetic_candles(n: int = 200) -> list[list[float]]:
    out: list[list[float]] = []
    px = 100.0
    for i in range(n):
        px *= 1 + 0.002 * math.sin(i / 7.0)
        out.append([float(i * 3_600_000), px, px * 1.01, px * 0.99, px * (1 + 0.001 * math.cos(i / 5.0)), 1000.0 + i])
    return out


# ---------------------------------------------------------------------------
# Symbol / timeframe mapping (pure)
# ---------------------------------------------------------------------------

class TestMapping:
    @pytest.mark.parametrize(
        "symbol,expected",
        [("BTC/USDT", "BTC-USDT"), ("eth/usdt", "ETH-USDT"), ("BTC/USDT:USDT", "BTC-USDT")],
    )
    def test_inst_id(self, symbol, expected):
        assert okx_data.to_okx_inst_id(symbol) == expected

    @pytest.mark.parametrize(
        "tf,expected",
        [("4h", "4H"), ("1h", "1H"), ("1d", "1D"), ("15m", "15m"), ("1w", "1W")],
    )
    def test_bar(self, tf, expected):
        assert okx_data.to_okx_bar(tf) == expected


# ---------------------------------------------------------------------------
# OKX-tool catalogue invariant (pure)
# ---------------------------------------------------------------------------

class TestOKXCatalogueInvariant:
    def test_assert_okx_readonly_passes(self):
        okx_data.assert_okx_readonly()

    def test_names_prefixed_and_non_executable(self):
        for t in okx_data.OKX_DATA_TOOLS:
            assert t["mcp_name"].startswith("runeclaw_okx_")
            assert "execute" not in t["mcp_name"].lower()
            assert t["skill_name"] in okx_data.OKX_SKILL_NAMES

    def test_skill_instances_match_catalogue(self):
        instance_names = {s.name for s in okx_data.okx_skill_instances()}
        assert instance_names == set(okx_data.OKX_SKILL_NAMES)


# ---------------------------------------------------------------------------
# Candle fetch/parse (network mocked)
# ---------------------------------------------------------------------------

class TestFetchCandles:
    def test_parses_newest_first_into_ascending_ohlcv(self, monkeypatch):
        import asyncio

        # OKX returns newest-first rows with 9 fields; we keep OHLCV, reverse.
        async def fake_payload(symbol, timeframe, limit):
            return {
                "code": "0",
                "msg": "",
                "data": [
                    ["3000", "30", "31", "29", "30.5", "9", "x", "x", "1"],
                    ["2000", "20", "21", "19", "20.5", "8", "x", "x", "1"],
                    ["1000", "10", "11", "9", "10.5", "7", "x", "x", "1"],
                ],
            }

        monkeypatch.setattr(okx_data, "_get_candles_payload", fake_payload)
        candles = asyncio.run(okx_data.fetch_okx_candles("BTC/USDT", "4h", 3))
        assert [c[0] for c in candles] == [1000.0, 2000.0, 3000.0]  # ascending
        assert all(len(c) == 6 for c in candles)  # OHLCV only
        assert candles[0] == [1000.0, 10.0, 11.0, 9.0, 10.5, 7.0]

    def test_okx_error_code_raises(self, monkeypatch):
        import asyncio

        async def fake_payload(symbol, timeframe, limit):
            return {"code": "51001", "msg": "Instrument doesn't exist", "data": []}

        monkeypatch.setattr(okx_data, "_get_candles_payload", fake_payload)
        with pytest.raises(okx_data.OKXDataError, match="51001"):
            asyncio.run(okx_data.fetch_okx_candles("NOPE/USDT", "4h", 3))


# ---------------------------------------------------------------------------
# End-to-end dispatch through the extended server (network mocked)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_RUNECLAW, reason="RUNECLAW submodule not importable")
class TestOKXToolDispatch:
    def _server(self, monkeypatch, token="okx-token"):
        import bot.mcp.server as mcp_server

        async def fake_fetch(symbol, timeframe="4h", limit=300):
            return _synthetic_candles(200)

        monkeypatch.setattr(okx_data, "fetch_okx_candles", fake_fetch)
        monkeypatch.setattr(mcp_server, "_MCP_AUTH_TOKEN", token)
        from runeclaw_okx.extended_server import build_extended_server

        return build_extended_server(), token

    @pytest.mark.parametrize("tool", ["runeclaw_okx_quant", "runeclaw_okx_backtest"])
    def test_okx_tool_returns_derived_envelope(self, monkeypatch, tool):
        import asyncio

        srv, token = self._server(monkeypatch)
        r = asyncio.run(srv.call_tool(tool, {"symbol": "BTC/USDT", "timeframe": "4h"}, auth_token=token))
        assert r["status"] == "success"
        payload = json.loads(r["result"])
        # Derived analysis only — the raw OKX candles must NOT be echoed back.
        assert payload["source"] == "okx-public-market-data"
        assert "_note" in payload
        assert "candles" not in payload and "ohlcv" not in payload

    def test_okx_tool_enforces_auth(self, monkeypatch):
        import asyncio

        srv, _ = self._server(monkeypatch)
        r = asyncio.run(srv.call_tool("runeclaw_okx_quant", {"symbol": "BTC/USDT"}, auth_token="wrong"))
        assert r["status"] == "error"
        assert "Authentication" in r["result"]

    def test_okx_tools_listed(self, monkeypatch):
        import asyncio

        srv, _ = self._server(monkeypatch)
        names = {t["name"] for t in asyncio.run(srv.list_tools())}
        assert {"runeclaw_okx_quant", "runeclaw_okx_backtest"} <= names
