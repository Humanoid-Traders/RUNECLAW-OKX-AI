#!/usr/bin/env python3
"""
Generate the OKX AI **A2MCP** (Agent-to-MCP) service manifest for RUNECLAW.

The tool list + JSON Schemas come straight from RUNECLAW's read-only
``TOOL_CATALOGUE`` (via the same ``_build_tool_schema`` the server uses for
``list_tools()``), so the manifest can never drift from what the server actually
serves — and can never list an execution tool, because the catalogue has none.

Usage::

    python scripts/generate_a2mcp_manifest.py            # write okx-ai/manifest.json
    python scripts/generate_a2mcp_manifest.py --check    # fail if the file is stale

Requires the RUNECLAW submodule on the path (conftest / PYTHONPATH=vendor/runeclaw).

NOTE: The field layout below is a DRAFT modelled on OKX AI's A2MCP description
(fixed price per call, settled via the OKX Payment SDK). Confirm the exact
provider-side schema against OKX's ASP spec before registering — see
``okx-ai/README.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Per-call price (string, minor-unit-safe) keyed by MCP tool. Flat default; the
# heavier full-universe scan / backtest / quant work cost a little more. Adjust
# before listing.
_DEFAULT_PRICE = "0.01"
_PER_TOOL_PRICE = {
    "runeclaw_fullscan": "0.05",
    "runeclaw_backtest": "0.05",
    "runeclaw_shield": "0.02",
    "runeclaw_quant": "0.05",
    "runeclaw_walkforward": "0.05",
    "runeclaw_event_risk": "0.02",
}

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MANIFEST_PATH = os.path.join(_ROOT, "okx-ai", "manifest.json")

# Make `runeclaw_okx` (repo root) and `bot` (submodule) importable when run
# directly, so callers don't have to pre-set PYTHONPATH.
for _p in (_ROOT, os.path.join(_ROOT, "vendor", "runeclaw")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


def build_manifest() -> dict:
    from bot.mcp.server import MCPToolDef, MCPToolParam, RuneClawMCPServer, TOOL_CATALOGUE

    from runeclaw_okx.extended_server import EXTENDED_TOOLS, assert_extended_readonly

    assert_extended_readonly()
    extended_defs = tuple(
        MCPToolDef(
            mcp_name=t["mcp_name"],
            skill_name=t["skill_name"],
            description=t["description"],
            params=tuple(MCPToolParam(**p) for p in t["params"]),
        )
        for t in EXTENDED_TOOLS
    )
    all_defs = tuple(TOOL_CATALOGUE) + extended_defs

    tools = []
    for tdef in all_defs:
        schema = RuneClawMCPServer._build_tool_schema(tdef)
        tools.append(
            {
                "name": schema["name"],
                "description": schema["description"],
                "inputSchema": schema["inputSchema"],
                "price": _PER_TOOL_PRICE.get(schema["name"], _DEFAULT_PRICE),
                "readOnly": True,
            }
        )

    return {
        "_schema": "okx-ai/a2mcp@draft",
        "_notes": (
            "DRAFT field layout — confirm against OKX's ASP / A2MCP provider spec "
            "before registering. tools[] is generated from RUNECLAW's read-only "
            "catalogue; do not hand-edit. See okx-ai/README.md."
        ),
        "service": {
            "name": "RUNECLAW Analysis",
            "type": "a2mcp",
            "version": "0.1.0",
            "description": (
                "Read-only crypto market analysis, risk evaluation (RUNECLAW Shield, "
                "21 fail-closed checks), macro-event risk state, and synthetic "
                "backtests, exposed as MCP tools. Analysis only — no trade execution."
            ),
            "provider": {
                "name": "<your-provider-name>",
                "contact": "<your-contact>",
                "agenticWallet": "<set-during-okx-registration>",
            },
            "endpoint": {
                "transport": "streamable-http",
                "url": "https://<your-public-host>/mcp",
                "healthcheck": "https://<your-public-host>/healthz",
                "auth": "bearer",
            },
            "pricing": {
                "model": "per_call",
                "currency": "USDC",
                "defaultPrice": _DEFAULT_PRICE,
                "settlement": "okx-payment-sdk",
            },
            "tools": tools,
        },
    }


def _serialize(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if okx-ai/manifest.json is missing or stale.",
    )
    args = parser.parse_args(argv)

    rendered = _serialize(build_manifest())

    if args.check:
        if not os.path.exists(_MANIFEST_PATH):
            print("manifest.json is missing; run generate_a2mcp_manifest.py", file=sys.stderr)
            return 1
        with open(_MANIFEST_PATH, encoding="utf-8") as fh:
            current = fh.read()
        if current != rendered:
            print("manifest.json is stale; regenerate it", file=sys.stderr)
            return 1
        print("manifest.json is up to date.")
        return 0

    os.makedirs(os.path.dirname(_MANIFEST_PATH), exist_ok=True)
    with open(_MANIFEST_PATH, "w", encoding="utf-8") as fh:
        fh.write(rendered)
    print(f"Wrote {_MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
