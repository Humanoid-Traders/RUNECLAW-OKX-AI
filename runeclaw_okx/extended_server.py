"""
Extended read-only MCP tool surface for RUNECLAW → OKX AI.

RUNECLAW's ``bot/mcp/server.py`` exposes 9 read-only tools, but its skill registry
holds many more *already-built, read-only* capabilities that aren't wired to MCP
(quant report, walk-forward validation, rejection explainer, macro briefs, …).
This module layers those in **from the OKX side, without modifying RUNECLAW**:
``build_extended_server()`` returns a ``RuneClawMCPServer`` subclass whose
``list_tools`` / ``call_tool`` also serve the extended catalogue, reusing
RUNECLAW's existing auth, validation, bounds, and skill-registry dispatch.

Every extended tool maps to a **read-only** skill. The catalogue below is pure
data (no RUNECLAW import), so the analysis-only invariant over it is testable even
without the submodule. ``EXECUTION_SKILLS`` is the firewall: a build fails closed
if any extended tool ever points at an execution/state-mutating skill.
"""

from __future__ import annotations

import json
from typing import Any

from runeclaw_okx.attestation import (
    ATTEST_TOOL_NAMES,
    ATTEST_TOOLS,
    assert_attest_readonly,
    get_attestor,
)
from runeclaw_okx.okx_data import (
    OKX_DATA_TOOLS,
    assert_okx_readonly,
    okx_skill_instances,
)

# Skills that can place/confirm trades or mutate live/breaker state. An extended
# tool must NEVER map to one of these (asserted at build + in tests).
EXECUTION_SKILLS: frozenset[str] = frozenset(
    {
        "execute_paper_trade",
        "run_strategy",
        "halt",
        "kill_switch",
        "request_live_approval",
        "feedback",
    }
)

# Vetted read-only skills the extended surface is allowed to expose.
READONLY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "quant_analyze",
        "walk_forward",
        "whynot",
        "check_event_risk",
        "macro_brief",
        "rejected_trades",
        "patterns",
    }
)

# Pure-data tool catalogue. Each entry mirrors RUNECLAW's MCPToolDef shape; params
# follow MCPToolParam (name/type/description/required/default). Omitting `default`
# means "don't inject a default" — important for optional free-text args like a
# `whynot` symbol, so the strict symbol validator isn't run on an empty string.
EXTENDED_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "mcp_name": "runeclaw_quant",
        "skill_name": "quant_analyze",
        "description": (
            "Quant report for a symbol: market regime, GARCH volatility forecast, "
            "Hurst exponent, a multi-factor edge score and a hard edge-gate "
            "(read-only; produces no trades)."
        ),
        "params": (
            {
                "name": "symbol",
                "type": "string",
                "description": "Trading pair, e.g. 'BTC/USDT'.",
                "required": False,
                "default": "BTC/USDT",
            },
            {
                "name": "timeframe",
                "type": "string",
                "description": "Candle timeframe, e.g. '1h', '4h', '1d'.",
                "required": False,
                "default": "4h",
            },
        ),
    },
    {
        "mcp_name": "runeclaw_walkforward",
        "skill_name": "walk_forward",
        "description": (
            "Walk-forward backtest with anchored-expanding train / rolling "
            "out-of-sample folds and an embargo gap; returns the overfit (train-test) "
            "gap, consistency score and per-bucket confidence calibration "
            "(synthetic data, read-only)."
        ),
        "params": (
            {
                "name": "bars",
                "type": "integer",
                "description": "OHLCV bars of synthetic data (max 5000).",
                "required": False,
                "default": 1440,
            },
            {
                "name": "seed",
                "type": "integer",
                "description": "Random seed for reproducible synthetic data.",
                "required": False,
                "default": 42,
            },
            {
                "name": "folds",
                "type": "integer",
                "description": "Number of walk-forward folds (1-10).",
                "required": False,
                "default": 3,
            },
        ),
    },
    {
        "mcp_name": "runeclaw_whynot",
        "skill_name": "whynot",
        "description": (
            "Explain why recent trade ideas were rejected by the risk engine, "
            "optionally filtered to one symbol. Read-only."
        ),
        "params": (
            {
                "name": "symbol",
                "type": "string",
                "description": "Optional trading pair to filter, e.g. 'BTC/USDT'.",
                "required": False,
            },
        ),
    },
    {
        "mcp_name": "runeclaw_event_risk",
        "skill_name": "check_event_risk",
        "description": (
            "Macro-event risk for a given symbol: upcoming high-impact events and "
            "the current event-risk state. Read-only."
        ),
        "params": (
            {
                "name": "symbol",
                "type": "string",
                "description": "Trading pair, e.g. 'BTC/USDT'.",
                "required": True,
            },
        ),
    },
    {
        "mcp_name": "runeclaw_macro_brief",
        "skill_name": "macro_brief",
        "description": (
            "Macro window status: the current macro-event risk state and the next "
            "scheduled events. Read-only."
        ),
        "params": (),
    },
    {
        "mcp_name": "runeclaw_rejected",
        "skill_name": "rejected_trades",
        "description": (
            "Recent trade ideas rejected by the risk engine, with the failing "
            "checks. Read-only."
        ),
        "params": (
            {
                "name": "count",
                "type": "integer",
                "description": "How many recent rejections to return (1-50).",
                "required": False,
                "default": 5,
            },
        ),
    },
    {
        "mcp_name": "runeclaw_patterns",
        "skill_name": "patterns",
        "description": (
            "Chart / market patterns detected across the scanned universe. Read-only."
        ),
        "params": (),
    },
)

# Extra integer bounds for extended params not covered by RUNECLAW's own guard
# (which clamps `bars` and allow-lists `mode`). key -> (min, max).
_EXTRA_BOUNDS: dict[str, tuple[int, int]] = {
    "folds": (1, 10),
    "count": (1, 50),
    "limit": (1, 300),
}


def assert_extended_readonly() -> None:
    """Fail closed if any extended tool maps outside the read-only allow-list."""
    seen: set[str] = set()
    for tool in EXTENDED_TOOLS:
        name = tool["mcp_name"]
        skill = tool["skill_name"]
        if name in seen:
            raise RuntimeError(f"Duplicate extended tool name: {name}")
        seen.add(name)
        if "execute" in name.lower():
            raise RuntimeError(f"Extended tool name looks executable: {name}")
        if skill in EXECUTION_SKILLS:
            raise RuntimeError(
                f"Extended tool '{name}' maps to execution skill '{skill}'"
            )
        if skill not in READONLY_ALLOWLIST:
            raise RuntimeError(
                f"Extended tool '{name}' maps to non-allow-listed skill '{skill}'"
            )
    # The OKX-data and attestation tools are read-only by construction; validate too.
    assert_okx_readonly()
    assert_attest_readonly()


def build_extended_server(rc_server: Any | None = None) -> Any:
    """Construct a RuneClawMCPServer subclass that also serves EXTENDED_TOOLS.

    Imports RUNECLAW lazily. ``assert_extended_readonly()`` runs first, so a
    misconfigured catalogue can never produce a server that exposes execution.
    """
    assert_extended_readonly()

    from bot.mcp.server import MCPToolDef, MCPToolParam, RuneClawMCPServer

    def _to_defs(catalogue: tuple[dict[str, Any], ...]) -> tuple[Any, ...]:
        return tuple(
            MCPToolDef(
                # Attestation meta-tools have no backing skill; they're handled in
                # the call_tool override, so use a placeholder skill_name.
                mcp_name=t["mcp_name"],
                skill_name=t.get("skill_name", "_" + t["mcp_name"]),
                description=t["description"],
                params=tuple(MCPToolParam(**p) for p in t["params"]),
            )
            for t in catalogue
        )

    defs = _to_defs(EXTENDED_TOOLS) + _to_defs(OKX_DATA_TOOLS) + _to_defs(ATTEST_TOOLS)
    okx_skills = okx_skill_instances()
    MCPResponse = __import__("bot.mcp.server", fromlist=["MCPResponse"]).MCPResponse

    class _ExtendedRuneClawMCPServer(RuneClawMCPServer):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            # Register the OKX-data skills so call_tool can dispatch them through
            # the same auth/validation/error path as every other tool.
            for skill in okx_skills:
                self._registry.register(skill)
            # Make the extended + OKX tools dispatchable (call_tool uses _tool_index).
            for d in defs:
                self._tool_index[d.mcp_name] = d

        async def list_tools(self) -> list[dict[str, Any]]:
            base = await super().list_tools()
            return base + [self._build_tool_schema(d) for d in defs]

        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any] | None = None,
            auth_token: str | None = None,
        ) -> dict[str, Any]:
            # Clamp extended integer params the base guard doesn't cover.
            args = dict(arguments or {})
            for key, (lo, hi) in _EXTRA_BOUNDS.items():
                if key in args:
                    try:
                        args[key] = max(lo, min(int(args[key]), hi))
                    except (ValueError, TypeError):
                        pass  # base call_tool returns a structured type error
            if name in ATTEST_TOOL_NAMES:
                return await self._handle_attest(name, args, auth_token)
            return await super().call_tool(name, args, auth_token=auth_token)

        async def _handle_attest(
            self, name: str, args: dict[str, Any], auth_token: str | None
        ) -> dict[str, Any]:
            # Same fail-closed auth as every other tool (the meta-tools bypass the
            # skill path, so the check is replicated here).
            import hmac

            import bot.mcp.server as _mcp

            if not auth_token or not hmac.compare_digest(auth_token, _mcp._MCP_AUTH_TOKEN):
                return MCPResponse(
                    status="error", tool=name,
                    result="Authentication required. Provide a valid auth_token.",
                ).to_dict()

            attestor = get_attestor()
            if name == "runeclaw_attest_key":
                return MCPResponse(
                    status="success", tool=name, result=json.dumps(attestor.key_info())
                ).to_dict()

            # runeclaw_signed: run a read-only tool, sign {request, response}.
            inner_tool = args.get("tool")
            inner_args = args.get("arguments") or {}
            if not inner_tool or not isinstance(inner_tool, str):
                return MCPResponse(
                    status="error", tool=name, result="Missing required parameter: tool"
                ).to_dict()
            if inner_tool in ATTEST_TOOL_NAMES:
                return MCPResponse(
                    status="error", tool=name,
                    result="Cannot sign attestation meta-tools (no recursion).",
                ).to_dict()
            if inner_tool not in self._tool_index:
                return MCPResponse(
                    status="error", tool=name, result=f"Unknown tool '{inner_tool}'.",
                ).to_dict()

            inner = await self.call_tool(inner_tool, inner_args, auth_token=auth_token)
            request = {"tool": inner_tool, "arguments": inner_args}
            attestation = attestor.attest({"request": request, "response": inner})
            return MCPResponse(
                status="success", tool=name,
                result=json.dumps(
                    {"request": request, "response": inner, "attestation": attestation},
                    default=str,
                ),
            ).to_dict()

    if rc_server is not None:
        return rc_server
    return _ExtendedRuneClawMCPServer()
