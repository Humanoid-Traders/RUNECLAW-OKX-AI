# RUNECLAW → OKX AI

Analysis-only **Model Context Protocol (MCP)** transport that exposes RUNECLAW's
existing read-only market-analysis, risk-evaluation, and backtest tools to the
**OKX AI** agent marketplace — and to any MCP client (Claude Code, Codex, Hermes,
OpenClaw) — over stdio.

> **Read-only by design.** This service offers a callable *signal / analysis /
> safety* window into RUNECLAW's brain. It **cannot** place, size, or confirm a
> live trade. No wallet, on-chain, or stablecoin-settlement surface is involved.

This implements **PR 1–3 + PR 5** of the plan in
[`vendor/runeclaw/docs/OKX_AI_MCP_INTEGRATION.md`](vendor/runeclaw/docs/OKX_AI_MCP_INTEGRATION.md):
the stdio transport adapter, the analysis-only invariant and fail-closed auth, the
streamable-HTTP transport for a network-reachable endpoint, and a
[`skills/`](skills/) pack that fronts the analysis on OKX AI / Onchain OS.

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

**Base (RUNECLAW's catalogue):** `runeclaw_scan`, `runeclaw_analyze`,
`runeclaw_risk`, `runeclaw_portfolio`, `runeclaw_explain`, `runeclaw_macro`,
`runeclaw_shield` (RUNECLAW Shield's fail-closed pre-trade risk checks — 23 in the
current engine; the served tool description still says 21, see
[`docs/OKX_OPPORTUNITIES.md`](docs/OKX_OPPORTUNITIES.md)), `runeclaw_fullscan`,
`runeclaw_backtest`.

**Extended (layered in by this repo, `runeclaw_okx/extended_server.py`):**
`runeclaw_quant` (regime / GARCH vol / Hurst / edge-gate), `runeclaw_walkforward`
(overfit-aware backtest validation), `runeclaw_whynot`, `runeclaw_event_risk`,
`runeclaw_macro_brief`, `runeclaw_rejected`, `runeclaw_patterns`.

**OKX market data (`runeclaw_okx/okx_data.py`):** `runeclaw_okx_quant` and
`runeclaw_okx_backtest` run RUNECLAW's quant report / strategy backtest on **OKX**
public market data (not just Bitget). They return **derived analysis only** — never
the raw OKX candles (see the data-redistribution note in
[`docs/OKX_OPPORTUNITIES.md`](docs/OKX_OPPORTUNITIES.md)). No OKX API key required.

**Verifiable analysis (`runeclaw_okx/attestation.py`):** `runeclaw_signed` runs any
read-only tool and returns its result with an **Ed25519 signature** over
`{request, response}` — a portable receipt that an agent (or an OKX Evaluator in a
dispute) can independently verify that RUNECLAW produced exactly that output.
`runeclaw_attest_key` returns the public key + verification recipe. Set a persistent
signing key with `MCP_ATTEST_PRIVATE_KEY` (base64 32-byte seed), else a per-process
ephemeral key is used.

20 read-only tools in total. There is **no** `runeclaw_execute`, and a pure
analysis-only invariant test guarantees no tool can map to an execution skill.

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

### Streamable-HTTP transport (network endpoint)

For a hosted, network-reachable endpoint (e.g. OKX AI's Agent-to-MCP, pay-per-call
model), serve the same read-only tools over streamable HTTP:

```bash
export MCP_AUTH_TOKEN="$(openssl rand -hex 32)"
python -m runeclaw_okx.transport --transport http --host 127.0.0.1 --port 8765
```

- **`GET /healthz`** — unauthenticated liveness probe (`{"status":"ok"}`).
- **`/mcp`** — the MCP streamable-HTTP endpoint. Every request requires
  `Authorization: Bearer $MCP_AUTH_TOKEN` (hmac-compared, fail-closed → 401) and is
  rate-limited per token (→ 429 with `Retry-After`).

| Env var | Default | Purpose |
|---|---|---|
| `MCP_AUTH_TOKEN` | *(required)* | Bearer token; server refuses to start without it. |
| `MCP_HTTP_HOST` / `--host` | `127.0.0.1` | Bind address. **Keep on localhost.** |
| `MCP_HTTP_PORT` / `--port` | `8765` | Bind port. |
| `MCP_HTTP_RPM` / `--rpm` | `120` | Per-token requests/minute. |
| `MCP_HTTP_ALLOWED_HOSTS` | localhost | Comma-separated `Host` allow-list (DNS-rebinding protection). |
| `MCP_HTTP_ALLOWED_ORIGINS` | *(none)* | Comma-separated `Origin` allow-list. |

**Bind localhost; terminate TLS at a reverse proxy.** The server binds `127.0.0.1`
by default and does not speak TLS. For a public endpoint, front it with nginx/Caddy
handling TLS and forwarding to `127.0.0.1:8765`, and add the public hostname to
`MCP_HTTP_ALLOWED_HOSTS`. Issue a **dedicated** token for the public endpoint
(distinct from any internal one) and rotate it.

### Skill pack for OKX AI / Onchain OS (PR 5)

[`skills/`](skills/) packages RUNECLAW's read-only analysis as Markdown+YAML
*skills* — `runeclaw-shield` and `runeclaw-analyze` — so OKX AI agents (OpenClaw,
Hermes, Claude Code, Codex) can discover and use them in natural language. Each
skill points the agent at the MCP server above and fronts the analysis only; there
is no execution path. See [`skills/README.md`](skills/README.md) for the format,
distribution (`npx skills add okx/<pack>`), and the open submission questions.

### OKX AI A2MCP registration artifacts (PR 4)

[`okx-ai/`](okx-ai/) holds the registration-ready artifacts for listing as an
**ASP → Agent-to-MCP** provider: a generated [`manifest.json`](okx-ai/manifest.json)
(service descriptor + per-call pricing + the nine tool schemas) and an
**off-by-default OKX Payment SDK seam** in the HTTP transport (`PaymentVerifier` /
`PaymentASGIMiddleware` → HTTP 402; `MCP_REQUIRE_PAYMENT` fails closed without a
verifier). These are **repo-side only** — no wallet, no live registration. The
actual wallet login + ASP registration is an operator step on an OKX-connected
agent; see [`okx-ai/README.md`](okx-ai/README.md). The payment/wallet surface
crosses the plan's "no wallet surface" line and needs a risk review before going
live (`vendor/runeclaw/docs/OKX_AI_MCP_INTEGRATION.md` §5/§7).

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