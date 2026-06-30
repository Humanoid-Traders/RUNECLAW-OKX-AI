"""
Tests for the extended read-only MCP tool surface (runeclaw_okx/extended_server.py).

The analysis-only invariant over EXTENDED_TOOLS is pure (always runs) — it's the
firewall guaranteeing the layered tools can never reach execution. Dispatch /
auth / bounds tests need the RUNECLAW submodule and the `mcp`-less in-process
server, and skip cleanly without it.
"""

from __future__ import annotations

import importlib.util

import pytest

from runeclaw_okx import extended_server as ext

_HAS_RUNECLAW = importlib.util.find_spec("bot") is not None


# ---------------------------------------------------------------------------
# Analysis-only invariant over the extended catalogue (pure)
# ---------------------------------------------------------------------------

class TestExtendedCatalogueInvariant:
    def test_assert_extended_readonly_passes(self):
        ext.assert_extended_readonly()  # must not raise

    def test_no_extended_tool_maps_to_an_execution_skill(self):
        for t in ext.EXTENDED_TOOLS:
            assert t["skill_name"] not in ext.EXECUTION_SKILLS

    def test_every_extended_skill_is_allow_listed(self):
        for t in ext.EXTENDED_TOOLS:
            assert t["skill_name"] in ext.READONLY_ALLOWLIST

    def test_names_are_unique_prefixed_and_non_executable(self):
        names = [t["mcp_name"] for t in ext.EXTENDED_TOOLS]
        assert len(names) == len(set(names))
        for n in names:
            assert n.startswith("runeclaw_")
            assert "execute" not in n.lower()

    def test_assert_fails_closed_if_execution_skill_sneaks_in(self, monkeypatch):
        bad = ext.EXTENDED_TOOLS + (
            {"mcp_name": "runeclaw_x", "skill_name": "execute_paper_trade", "params": ()},
        )
        monkeypatch.setattr(ext, "EXTENDED_TOOLS", bad)
        with pytest.raises(RuntimeError, match="execution skill"):
            ext.assert_extended_readonly()


# ---------------------------------------------------------------------------
# Dispatch / auth / bounds (need the RUNECLAW submodule)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_RUNECLAW, reason="RUNECLAW submodule not importable")
class TestExtendedServer:
    def _server(self, monkeypatch, token="ext-token"):
        import bot.mcp.server as mcp_server

        # The constructor + auth compare against this module global.
        monkeypatch.setattr(mcp_server, "_MCP_AUTH_TOKEN", token)
        return ext.build_extended_server(), mcp_server, token

    def test_list_tools_includes_base_and_extended(self, monkeypatch):
        import asyncio

        from runeclaw_okx.attestation import ATTEST_TOOLS
        from runeclaw_okx.okx_data import OKX_DATA_TOOLS

        srv, mcp_server, _ = self._server(monkeypatch)
        names = {t["name"] for t in asyncio.run(srv.list_tools())}
        base = {t.mcp_name for t in mcp_server.TOOL_CATALOGUE}
        extended = {t["mcp_name"] for t in ext.EXTENDED_TOOLS}
        okx = {t["mcp_name"] for t in OKX_DATA_TOOLS}
        attest = {t["mcp_name"] for t in ATTEST_TOOLS}
        assert base <= names and extended <= names and okx <= names and attest <= names
        assert len(names) == len(base | extended | okx | attest)
        assert "runeclaw_execute" not in names
        assert not any("execute" in n.lower() for n in names)

    def test_extended_tool_dispatches(self, monkeypatch):
        import asyncio

        srv, _, token = self._server(monkeypatch)
        r = asyncio.run(srv.call_tool("runeclaw_macro_brief", {}, auth_token=token))
        assert r["status"] == "success"

    def test_extended_tool_enforces_auth(self, monkeypatch):
        import asyncio

        srv, _, _ = self._server(monkeypatch)
        r = asyncio.run(srv.call_tool("runeclaw_quant", {"symbol": "BTC/USDT"}, auth_token="wrong"))
        assert r["status"] == "error"
        assert "Authentication" in r["result"]

    def test_execution_tool_is_not_dispatchable(self, monkeypatch):
        import asyncio

        srv, _, token = self._server(monkeypatch)
        r = asyncio.run(srv.call_tool("runeclaw_execute", {}, auth_token=token))
        assert r["status"] == "error"
        assert "Unknown tool" in r["result"]

    def test_folds_param_is_clamped(self, monkeypatch):
        import asyncio

        srv, _, token = self._server(monkeypatch)
        # An absurd fold count must not blow up — it is clamped, call still succeeds.
        r = asyncio.run(
            srv.call_tool("runeclaw_walkforward", {"bars": 200, "folds": 100000}, auth_token=token)
        )
        assert r["status"] == "success"
