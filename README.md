# RUNECLAW → OKX AI

Analysis-only **Model Context Protocol (MCP)** transport that exposes RUNECLAW's
existing read-only market-analysis, risk-evaluation, and backtest tools to the
**OKX AI** agent marketplace — and to any MCP client (Claude Code, Codex, Hermes,
OpenClaw) — over stdio.

> **Read-only by design.** This service offers a callable *signal / analysis /
> safety* window into RUNECLAW's brain. It **cannot** place, size, or confirm a
> live trade. No wallet, on-chain, or stablecoin-settlement surface is involved.

This implements **PR 1 + PR 2** of the plan in
[`vendor/runeclaw/docs/OKX_AI_MCP_INTEGRATION.md`](vendor/runeclaw/docs/OKX_AI_MCP_INTEGRATION.md):
the stdio transport adapter plus the analysis-only invariant and fail-closed auth.

## How it relates to RUNECLAW

RUNECLAW is the single source of truth and is pinned here as a **git submodule**
under [`vendor/runeclaw`](vendor/runeclaw). This repo adds only a thin adapter —
`runeclaw_okx/transport.py` — that wraps RUNECLAW's existing
`bot/mcp/server.py:RuneClawMCPServer` (nine read-only tools; trade execution
intentionally excluded) in the official `mcp` SDK. No RUNECLAW code is copied or
modified.

```
MCP client ──stdio──▶ runeclaw_okx.transport  (official mcp SDK Server)
                          • list_tools()  ─┐  delegate verbatim
                          • call_tool()  ──┤
                                           ▼
                       vendor/runeclaw  RuneClawMCPServer (read-only catalogue)
                                           │
                                           ▼
                                     SkillRegistry → RuneClawEngine (no executor)
```

## Exposed tools (all read-only)

`runeclaw_scan`, `runeclaw_analyze`, `runeclaw_risk`, `runeclaw_portfolio`,
`runeclaw_explain`, `runeclaw_macro`, `runeclaw_shield` (21 fail-closed risk
checks), `runeclaw_fullscan`, `runeclaw_backtest`. There is **no** `runeclaw_execute`.

## Analysis-only enforcement (defence in depth)

1. **Catalogue allow-list** — the adapter serves only RUNECLAW's read-only
   `TOOL_CATALOGUE`; there is no code path from MCP to `confirm_trade` / the executor.
2. **Invariant test** — `tests/test_mcp_transport.py` locks the exposed surface to
   the nine read-only tools and asserts no tool/skill resolves to the trade
   executor. The execution skill stays registered but unexposed, so a future
   catalogue edit that adds an execute path fails CI.
3. **Fail-closed `MCP_AUTH_TOKEN`** — the stdio transport forwards the env token
   into RUNECLAW's existing hmac-compared auth check; it refuses to start without one.
4. **`MCP_ALLOW_EXECUTE` must be unset** — a startup assertion (runs before auth
   and before any heavy import) refuses to serve with execution enabled.

## Setup

```bash
git clone --recurse-submodules <this repo>
cd runeclaw-okx-ai
# or, if already cloned without submodules:
git submodule update --init --recursive

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # RUNECLAW deps (from the submodule) + mcp
```

## Run

```bash
export MCP_AUTH_TOKEN="$(openssl rand -hex 32)"   # required; server refuses to start without it
# leave MCP_ALLOW_EXECUTE unset (the transport asserts it is unset)
python -m runeclaw_okx.transport                  # speaks MCP over stdio
```

Point any stdio MCP client at that command. Example client config:

```json
{
  "mcpServers": {
    "runeclaw": {
      "command": "python",
      "args": ["-m", "runeclaw_okx.transport"],
      "env": { "MCP_AUTH_TOKEN": "<your-token>" }
    }
  }
}
```

## Test

```bash
pip install -e ".[dev]"
pytest -q
```

The security-guard tests (`MCP_ALLOW_EXECUTE`, `MCP_AUTH_TOKEN`) need only the
standard library. The analysis-only invariant and end-to-end SDK-mapping tests
need the RUNECLAW submodule initialised (and, for the mapping tests, the `mcp`
SDK installed); they skip cleanly otherwise.

## Updating the pinned RUNECLAW

```bash
cd vendor/runeclaw && git fetch origin && git checkout <new-sha> && cd -
git add vendor/runeclaw && git commit -m "Bump RUNECLAW submodule"
```

## Out of scope (held per the plan, §7)

Streamable-HTTP transport (PR 3), the OKX AI registration manifest/docs (PR 4),
and the `agent-skills` packaging (PR 5) wait until OKX-side specifics — transport,
identity/registration, monetization, hosting — are confirmed.