"""
Validation for the OKX AI A2MCP service manifest (okx-ai/manifest.json) and its
generator (scripts/generate_a2mcp_manifest.py).

Structural checks are pure (always run). The catalogue cross-check and the
staleness check need the RUNECLAW submodule and skip cleanly without it.
"""

from __future__ import annotations

import importlib.util
import json
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MANIFEST = os.path.join(_ROOT, "okx-ai", "manifest.json")
_GENERATOR = os.path.join(_ROOT, "scripts", "generate_a2mcp_manifest.py")


def _load_manifest() -> dict:
    with open(_MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_a2mcp", _GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Structural (pure)
# ---------------------------------------------------------------------------

class TestManifestShape:
    def test_manifest_is_valid_json_and_a2mcp(self):
        m = _load_manifest()
        assert m["service"]["type"] == "a2mcp"
        assert m["service"]["pricing"]["model"] == "per_call"
        assert m["service"]["pricing"]["settlement"] == "okx-payment-sdk"

    def test_all_tools_readonly_with_price(self):
        tools = _load_manifest()["service"]["tools"]
        assert len(tools) >= 9  # 9 base + extended read-only tools
        for t in tools:
            assert {"name", "description", "inputSchema", "price", "readOnly"} <= set(t)
            assert t["readOnly"] is True
            assert isinstance(t["price"], str) and t["price"]

    def test_includes_the_extended_readonly_tools(self):
        from runeclaw_okx.extended_server import EXTENDED_TOOLS

        names = {t["name"] for t in _load_manifest()["service"]["tools"]}
        for t in EXTENDED_TOOLS:
            assert t["mcp_name"] in names

    def test_no_execution_tool_listed(self):
        names = [t["name"] for t in _load_manifest()["service"]["tools"]]
        assert "runeclaw_execute" not in names
        assert not any("execute" in n.lower() for n in names)


# ---------------------------------------------------------------------------
# Cross-check against the live RUNECLAW catalogue + staleness
# ---------------------------------------------------------------------------

class TestManifestMatchesCatalogue:
    def test_tool_names_match_catalogue(self):
        server = pytest.importorskip("bot.mcp.server")
        from runeclaw_okx.extended_server import EXTENDED_TOOLS

        expected = {t.mcp_name for t in server.TOOL_CATALOGUE} | {
            t["mcp_name"] for t in EXTENDED_TOOLS
        }
        manifest_names = {t["name"] for t in _load_manifest()["service"]["tools"]}
        assert manifest_names == expected

    def test_manifest_is_not_stale(self):
        pytest.importorskip("bot.mcp.server")
        gen = _load_generator()
        rendered = gen._serialize(gen.build_manifest())
        with open(_MANIFEST, encoding="utf-8") as fh:
            assert fh.read() == rendered, "manifest.json is stale — regenerate it"
