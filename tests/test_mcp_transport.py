"""
Tests for the analysis-only MCP stdio transport adapter (runeclaw_okx/transport.py).

The transport exposes RUNECLAW's read-only TOOL_CATALOGUE to external MCP clients
(OKX AI, Claude Code, Codex). These tests pin the security invariants that make
that safe:

  * the analysis-only invariant — no MCP tool name or skill can reach trade
    execution (defence in depth against a future catalogue edit);
  * the MCP_ALLOW_EXECUTE-must-be-unset startup assertion;
  * fail-closed MCP_AUTH_TOKEN at the transport boundary.

Layered availability:
  * the security-guard tests (MCP_ALLOW_EXECUTE / MCP_AUTH_TOKEN) depend only on
    the standard library and always run;
  * the analysis-only invariant + end-to-end SDK-mapping tests need the RUNECLAW
    submodule (``vendor/runeclaw``) importable and, for the mapping tests, the
    official ``mcp`` SDK installed — they skip cleanly otherwise.
"""

from __future__ import annotations

import importlib.util

import pytest

from runeclaw_okx import transport

_HAS_MCP_SDK = importlib.util.find_spec("mcp") is not None

# The exact read-only surface the transport is allowed to expose. Built-in tools
# (shield, fullscan) use leading-underscore skill names dispatched inside the
# server; the rest resolve through the SkillRegistry. Locking this set means a
# future catalogue edit that adds *anything* — especially an execute path — fails
# the suite and forces an explicit security review.
_EXPECTED_EXPOSED_SKILLS = {
    "scan_market",
    "analyze_asset",
    "check_risk",
    "get_portfolio",
    "explain_trade",
    "macro_calendar",
    "run_backtest",
    "_shield_evaluate",
    "_fullscan",
}

# Skills that can mutate trades / reach the executor and must NEVER be exposed.
_EXECUTION_SKILL_NAMES = {"execute_paper_trade"}


def _runeclaw():
    """Import the RUNECLAW pieces under test, or skip if the submodule is absent."""
    server = pytest.importorskip("bot.mcp.server")
    registry = pytest.importorskip("bot.skills.skill_registry")
    return server, registry


# ---------------------------------------------------------------------------
# Analysis-only invariant (defence in depth) — needs the RUNECLAW submodule
# ---------------------------------------------------------------------------

class TestAnalysisOnlyInvariant:
    def test_exposed_surface_is_exactly_the_readonly_catalogue(self):
        server, _ = _runeclaw()
        exposed = {t.skill_name for t in server.TOOL_CATALOGUE}
        assert exposed == _EXPECTED_EXPOSED_SKILLS

    def test_no_mcp_tool_maps_to_an_execution_skill(self):
        server, _ = _runeclaw()
        for tdef in server.TOOL_CATALOGUE:
            assert tdef.skill_name not in _EXECUTION_SKILL_NAMES, (
                f"MCP tool '{tdef.mcp_name}' exposes execution skill "
                f"'{tdef.skill_name}'"
            )

    def test_no_execute_named_mcp_tool(self):
        server, _ = _runeclaw()
        names = {t.mcp_name for t in server.TOOL_CATALOGUE}
        assert "runeclaw_execute" not in names
        assert not any("execute" in n.lower() for n in names)

    def test_execution_skill_is_registered_but_unexposed(self):
        # The deny-check is only meaningful if the execution skill actually
        # exists in the registry — confirm it does, and that MCP never lists it.
        server, registry = _runeclaw()
        reg = registry.build_default_registry()
        assert reg.get("execute_paper_trade") is not None
        exposed = {t.skill_name for t in server.TOOL_CATALOGUE}
        assert "execute_paper_trade" not in exposed

    def test_no_catalogued_skill_resolves_to_the_executor(self):
        server, registry = _runeclaw()
        reg = registry.build_default_registry()
        for tdef in server.TOOL_CATALOGUE:
            if tdef.skill_name.startswith("_"):
                continue  # built-in read-only shield / fullscan
            skill = reg.get(tdef.skill_name)
            assert skill is not None, f"{tdef.skill_name} not registered"
            assert not isinstance(skill, registry.ExecutePaperTradeSkill), (
                f"MCP tool '{tdef.mcp_name}' routes to the trade executor"
            )


# ---------------------------------------------------------------------------
# MCP_ALLOW_EXECUTE must be unset (fourth enforcement layer) — stdlib only
# ---------------------------------------------------------------------------

class TestExecuteFlagAssertion:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "On"])
    def test_assert_raises_when_execute_enabled(self, monkeypatch, value):
        monkeypatch.setenv("MCP_ALLOW_EXECUTE", value)
        with pytest.raises(RuntimeError, match="MCP_ALLOW_EXECUTE"):
            transport._assert_execute_disabled()

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
    def test_assert_passes_when_execute_disabled(self, monkeypatch, value):
        monkeypatch.setenv("MCP_ALLOW_EXECUTE", value)
        transport._assert_execute_disabled()  # must not raise

    def test_assert_passes_when_unset(self, monkeypatch):
        monkeypatch.delenv("MCP_ALLOW_EXECUTE", raising=False)
        transport._assert_execute_disabled()  # must not raise

    def test_build_server_refuses_when_execute_enabled(self, monkeypatch):
        # The execute guard runs before auth and before any heavy import, so this
        # fails closed regardless of token / SDK / submodule availability.
        monkeypatch.setenv("MCP_ALLOW_EXECUTE", "true")
        monkeypatch.setenv("MCP_AUTH_TOKEN", "secret")
        with pytest.raises(RuntimeError, match="MCP_ALLOW_EXECUTE"):
            transport.build_server()


# ---------------------------------------------------------------------------
# Fail-closed MCP_AUTH_TOKEN at the transport boundary — stdlib only
# ---------------------------------------------------------------------------

class TestTransportAuthFailClosed:
    def test_resolve_token_raises_without_token(self, monkeypatch):
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN"):
            transport._resolve_auth_token()

    def test_resolve_token_returns_configured_token(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_TOKEN", "a-secret-token")
        assert transport._resolve_auth_token() == "a-secret-token"

    def test_build_server_refuses_without_token(self, monkeypatch):
        monkeypatch.delenv("MCP_ALLOW_EXECUTE", raising=False)
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN"):
            transport.build_server()


# ---------------------------------------------------------------------------
# End-to-end SDK mapping — needs the RUNECLAW submodule AND the `mcp` SDK
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_MCP_SDK, reason="official `mcp` SDK not installed")
class TestSdkMapping:
    def _build(self, monkeypatch):
        _runeclaw()  # skip if the submodule isn't importable
        import bot.mcp.server as mcp_server

        monkeypatch.delenv("MCP_ALLOW_EXECUTE", raising=False)
        monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
        # Patch the module-level token the server compares against so the
        # forwarded token authenticates in-process.
        monkeypatch.setattr(mcp_server, "_MCP_AUTH_TOKEN", "test-token")
        return transport.build_server(), mcp_server

    def test_list_tools_advertises_exactly_the_catalogue(self, monkeypatch):
        import asyncio

        (server, _rc), mcp_server = self._build(monkeypatch)

        async def _run():
            return await mcp_server.RuneClawMCPServer().list_tools()

        expected = asyncio.run(_run())
        expected_names = {d["name"] for d in expected}
        assert expected_names == {t.mcp_name for t in mcp_server.TOOL_CATALOGUE}
        assert "runeclaw_execute" not in expected_names
        assert server.request_handlers, "no MCP request handlers registered"

    def test_call_tool_forwards_auth_and_returns_envelope(self, monkeypatch):
        import asyncio
        import json

        from mcp import types

        (server, _rc), _mcp_server = self._build(monkeypatch)
        call_handler = server.request_handlers[types.CallToolRequest]

        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="runeclaw_macro", arguments={}),
        )
        result = asyncio.run(call_handler(req))
        # CallToolResult.content carries our JSON envelope as a TextContent block.
        payload = json.loads(result.root.content[0].text)
        assert payload["tool"] == "runeclaw_macro"
        # Auth was forwarded from the env token → not an auth error.
        assert payload["status"] == "success"

    def test_call_tool_rejects_when_token_mismatches(self, monkeypatch):
        import asyncio
        import json

        from mcp import types

        # Build with one token, then flip the server's expected token so the
        # forwarded value no longer matches → fail-closed auth rejection.
        (server, _rc), mcp_server = self._build(monkeypatch)
        monkeypatch.setattr(mcp_server, "_MCP_AUTH_TOKEN", "different-token")
        call_handler = server.request_handlers[types.CallToolRequest]

        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="runeclaw_macro", arguments={}),
        )
        result = asyncio.run(call_handler(req))
        payload = json.loads(result.root.content[0].text)
        assert payload["status"] == "error"
        assert "Authentication required" in payload["result"]
