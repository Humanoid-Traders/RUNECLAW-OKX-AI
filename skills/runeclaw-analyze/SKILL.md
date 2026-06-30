---
name: runeclaw-analyze
description: Run RUNECLAW's AI analysis on a single crypto symbol (e.g. BTC/USDT) and get back a structured trade idea — direction, entry, stop-loss, take-profit, confidence and the reasoning/signals behind it. Use it to turn a symbol into a concrete, reviewable setup you can then validate with runeclaw-shield. Read-only and analysis-only: it produces a trade *idea*, never an order, and never places, sizes for execution, or confirms a live trade.
---

# RUNECLAW Analyze (analysis-only signal)

Turn a single symbol into a structured **trade idea**: direction, entry, stop-loss,
take-profit, confidence, and the signals/reasoning behind it. It produces an idea,
not an order — nothing here executes.

## When to use

- To get a concrete, reviewable setup for one symbol.
- As the first step before risk-gating the idea with the `runeclaw-shield` skill.

## Prerequisite: the RUNECLAW MCP server

This skill calls the **`runeclaw_analyze`** tool on the RUNECLAW MCP server. Add the
server to your MCP client first (stdio or streamable-HTTP), authenticated with a
bearer token. See <https://github.com/Humanoid-Traders/RUNECLAW-OKX-AI>. The server
exposes only read-only analysis tools; trade execution is intentionally not exposed.

## How to call

Invoke the `runeclaw_analyze` MCP tool with:

| Argument | Type | Required | Notes |
|---|---|---|---|
| `symbol` | string | yes | trading pair, e.g. `ETH/USDT` |

Example arguments:

```json
{ "symbol": "ETH/USDT" }
```

## Interpreting the result

The tool returns a structured trade idea (direction, entry, stop-loss, take-profit,
confidence, reasoning). Treat it as a *proposal*: pass it to `runeclaw-shield` for a
fail-closed risk verdict before relying on it. A low-confidence or
no-setup response means there is no actionable idea right now.

## Boundaries

This skill is analysis-only. It returns an idea; it cannot place, size for
execution, or confirm a live order, and it never touches a wallet or on-chain
settlement.
