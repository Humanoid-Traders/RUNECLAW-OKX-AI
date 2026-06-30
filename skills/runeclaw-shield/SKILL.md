---
name: runeclaw-shield
description: Run RUNECLAW Shield — 23 fail-closed pre-trade risk checks — on a proposed crypto trade (symbol, direction, entry, stop-loss, take-profit, confidence) and get an immutable approved/rejected verdict with per-check detail and a suggested position size. Use it before acting on any trade idea to validate risk/reward, stop placement, drawdown and circuit-breaker state. Read-only and analysis-only — it evaluates a proposal and returns a safety decision; it never places, sizes for execution, or confirms a live order.
---

# RUNECLAW Shield (analysis-only risk gate)

RUNECLAW Shield is a safety service: hand it a proposed trade and it returns an
immutable **approved / rejected** verdict from 23 fail-closed risk checks. It is
read-only — it judges a proposal, it does not execute anything.

## When to use

- Before you act on any trade idea (your own, or one from `runeclaw-analyze`).
- To sanity-check risk/reward, stop-loss placement, and current drawdown /
  circuit-breaker state.

## Prerequisite: the RUNECLAW MCP server

This skill calls the **`runeclaw_shield`** tool on the RUNECLAW MCP server. Add the
server to your MCP client first (stdio or streamable-HTTP), authenticated with a
bearer token. See <https://github.com/Humanoid-Traders/RUNECLAW-OKX-AI>. The server
exposes only read-only analysis tools; trade execution is intentionally not exposed.

## How to call

Invoke the `runeclaw_shield` MCP tool with:

| Argument | Type | Required | Notes |
|---|---|---|---|
| `symbol` | string | yes | e.g. `BTC/USDT` |
| `direction` | string | yes | `long` or `short` |
| `entry_price` | number | yes | proposed entry |
| `stop_loss` | number | yes | stop price |
| `take_profit` | number | yes | target price |
| `confidence` | number | no | signal confidence 0.0–1.0 (default 0.65) |

Example arguments:

```json
{
  "symbol": "BTC/USDT",
  "direction": "long",
  "entry_price": 65000,
  "stop_loss": 63500,
  "take_profit": 69000,
  "confidence": 0.7
}
```

## Interpreting the result

The tool returns a JSON envelope whose `result` contains:

- `approved` (bool) and `verdict` (`APPROVED` / `REJECTED`),
- `risk_reward`, `position_size_usd`,
- `checks_passed`, `checks_failed`, and `failed_checks` (which checks blocked it),
- `reason` (a human-readable summary).

Treat a `REJECTED` verdict as a hard stop: do not proceed with the trade.

## Boundaries

This skill is analysis-only. It cannot place, size for execution, or confirm a
live order, and it never touches a wallet or on-chain settlement.
