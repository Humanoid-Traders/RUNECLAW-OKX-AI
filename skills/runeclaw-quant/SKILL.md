---
name: runeclaw-quant
description: Run RUNECLAW's quant report on a crypto symbol (e.g. BTC/USDT) and get a structured read on market regime, a GARCH volatility forecast, the Hurst exponent (trending vs mean-reverting), a multi-factor edge score, and a hard pass/fail edge-gate. Use it to decide whether a market currently has a statistical edge worth trading before you form or risk-check an idea. Read-only and analysis-only: it reports quant state, never places, sizes for execution, or confirms a trade.
---

# RUNECLAW Quant (analysis-only statistical read)

Get a quant snapshot of one symbol — regime, volatility forecast, persistence, and a
factor-based edge score with a hard gate — so you can decide whether there's a
statistical edge before committing analysis or risk budget. It reports; it never trades.

## When to use

- Before `runeclaw-analyze` / `runeclaw-shield`, to screen whether a market is worth
  the deeper look (the edge-gate is a cheap first filter).
- To understand *why* a market is hard to trade (chop/range regime, anti-persistent
  Hurst, weak factors).

## Prerequisite: the RUNECLAW MCP server

This skill calls the **`runeclaw_quant`** tool on the RUNECLAW MCP server. Add the
server to your MCP client first (stdio or streamable-HTTP), authenticated with a
bearer token. See <https://github.com/Humanoid-Traders/RUNECLAW-OKX-AI>. The server
exposes only read-only analysis tools; trade execution is intentionally not exposed.

## How to call

Invoke the `runeclaw_quant` MCP tool with:

| Argument | Type | Required | Notes |
|---|---|---|---|
| `symbol` | string | no | trading pair, e.g. `BTC/USDT` (default `BTC/USDT`) |
| `timeframe` | string | no | candle timeframe, e.g. `1h`, `4h`, `1d` (default `4h`) |

Example arguments:

```json
{ "symbol": "SOL/USDT", "timeframe": "1h" }
```

## Interpreting the result

The report covers the market **regime**, a **GARCH volatility forecast**, the
**Hurst exponent** (>0.5 trending, <0.5 mean-reverting), per-factor scores, a
composite **edge score**, and an **edge-gate** pass/fail. A failed edge-gate means
there is no statistical edge right now — stand down rather than force a trade.

## Boundaries

This skill is analysis-only. It cannot place, size for execution, or confirm a live
order, and it never touches a wallet or on-chain settlement.
