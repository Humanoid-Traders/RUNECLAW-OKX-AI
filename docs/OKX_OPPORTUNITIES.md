# RUNECLAW × OKX — opportunity map &amp; roadmap

Strategy record for extending RUNECLAW into "the complete OKX version." Grounded in
a capability inventory of RUNECLAW (`vendor/runeclaw`) and a survey of the OKX agent
ecosystem (OKX AI marketplace, Onchain OS, Agent Payments Protocol, OKX DEX APIs).
Everything here respects the hard line: **analysis-only — no execution, no wallet,
no on-chain transactions from the OKX surface.**

## The two directions OKX opens up

RUNECLAW today **consumes Bitget data** and **exposes analysis**. OKX adds:

1. **OKX as a distribution + monetization channel** — A2MCP priced endpoint, a
   discoverable skill pack, per-call settlement. (Built: PR 1–5, plus the extended
   tool surface below.)
2. **OKX as a data source** — `onchainos-skills` / OKX DEX APIs give DEX market
   data, OHLC, smart-money/whale signals, sentiment across 20+ chains. RUNECLAW's
   analyzer/Shield/quant stack could run on OKX/on-chain markets, not just 67 Bitget
   pairs. (Not built — see Opportunity C and its legal gate.)

## Opportunities, ranked

| # | Opportunity | RUNECLAW brings | OKX surface | Role / revenue | Effort | Risk |
|---|---|---|---|---|---|---|
| **A** | Expose hidden read-only tools | quant report, walk-forward, whynot, macro briefs, rejections, patterns | A2MCP tools + skills + manifest | Per-call | Low | Low — **done this round** |
| **B** | Shield-as-a-Service | 23-check fail-closed risk verdict oracle | A2MCP, priced | Recurring per-call | Low | Low |
| **C** | Analyze OKX / on-chain markets | pattern + microstructure + quant stack | consume OKX public market data | Expands TAM | Med | ⚠️ data-redistribution clause — **CEX leg done** |
| **D** | A2A escrow deliverables | custom backtests, walk-forward of a user strategy, "red-team my strategy" (`red_team.py`) | A2A escrow on X Layer | Per-deliverable | Med | Med — needs wallet |
| **E** | Verifiable analysis | SHA-256 + Ed25519 audit chain | trust layer for disputes/Evaluators | Premium tier | Med | Low — **done** |
| **F** | Evaluator node | `critique.py` + `red_team.py` + Shield as adjudicator | Evaluator role, stake OKB | Arbitration bounties | High | High — opaque economics |

## Constraints that gate the above

- **OKX market-data redistribution clause (gates C).** OKX forbids reselling/
  redistributing its market data *verbatim* — or training a commercial model on it —
  **even from free endpoints**. Safe line: RUNECLAW emitting its **own derived
  verdicts/signals** computed from OKX data is fine; **passing OKX raw candles/quotes
  through** to customers needs OKX's written consent. Never build a "resell OKX data"
  feature.
- **Execution + wallet firewall.** RUNECLAW's only exchange wiring is **Bitget**, with
  **zero wallet/custody/on-chain code**. Adding OKX *data* is read-only and safe.
  Monetization (A2MCP payments, Agentic Wallet, ERC-8004 identity) crosses the **"no
  wallet surface" line** reserved for a risk review — it gates B/C/D/F going *live*,
  not building them.
- **Opaque economics.** No published marketplace take-rate/revenue-share. The
  "≥100 OKB" Evaluator stake is **unverified** (absent from the APP whitepaper).
  Model marketplace fees as unknown.

## Built in this round — Opportunity A (+ B positioning)

The extended read-only surface (`runeclaw_okx/extended_server.py`) layers 7 more
already-built, read-only RUNECLAW tools onto the MCP server **without modifying
RUNECLAW**, taking the served surface from 9 → 16 tools:

`runeclaw_quant` (regime/GARCH/Hurst/edge-gate), `runeclaw_walkforward`
(overfit-aware validation), `runeclaw_whynot`, `runeclaw_event_risk`,
`runeclaw_macro_brief`, `runeclaw_rejected`, `runeclaw_patterns`.

They reuse RUNECLAW's auth, validation, bounds, and skill dispatch; a pure
analysis-only invariant (`assert_extended_readonly` + tests) guarantees no extended
tool can ever map to an execution skill. The A2MCP manifest and the skill pack
(`skills/runeclaw-quant`) were extended to match.

## Shield check-count drift — fixed upstream (RUNECLAW #203)

RUNECLAW previously reported its Shield check count inconsistently: 23 (the engine /
`_TOTAL_RISK_CHECKS`, authoritative), 21 (the MCP tool description), and 18
(`getclaw_wrapper.py`). Reconciled upstream in **RUNECLAW #203** — the MCP
description now derives the count from `_TOTAL_RISK_CHECKS` (single source of truth)
and the stale literals are gone. The `vendor/runeclaw` submodule here is pinned past
that fix, so the served description and the A2MCP manifest now correctly read 23.

## Opportunity C — OKX data adapter (CEX leg built)

`runeclaw_okx/okx_data.py` fetches OKX's **public CEX market data** (`/api/v5/market/
candles`, no API key) and runs RUNECLAW's stateless analysis on it, exposed as two
read-only tools — `runeclaw_okx_quant` (quant report) and `runeclaw_okx_backtest`
(rule-based strategy backtest). RUNECLAW now analyses **OKX** markets, not just
Bitget.

**Data-clause compliance, by construction:** the tools return RUNECLAW's *derived*
output (a quant report / backtest metrics) and **never echo the raw OKX candles** —
a test asserts the response carries no `candles`/`ohlcv`. This stays on the safe
side of OKX's redistribution terms (derived signals OK; raw pass-through needs
consent). Remaining for C: the **DEX/on-chain leg** (`okx-dex-signal` smart-money,
`okx-dex-market` OHLC) needs an OKX Developer-Portal API key and the same
derived-only discipline.

## Opportunity E — verifiable analysis (built)

`runeclaw_okx/attestation.py` signs analysis with **Ed25519** (the same primitive as
RUNECLAW's audit-chain attestation) as a standalone, externally verifiable receipt:
`runeclaw_signed` runs any read-only tool and returns its result plus a signature
over `{request, response}`; `runeclaw_attest_key` publishes the public key + verify
recipe. Any Ed25519 library verifies it — no RUNECLAW code needed — which is exactly
what an OKB-staked Evaluator needs to adjudicate "did RUNECLAW really return this?".
The signing key is per-deployment (`MCP_ATTEST_PRIVATE_KEY`), ephemeral if unset.

## Suggested next steps (in order)

1. **Reconcile the Shield count** upstream in RUNECLAW (small, correctness).
2. **Opportunity C — DEX leg**: add the keyed OKX DEX data sources (smart-money /
   on-chain OHLC) behind the same derived-only adapter (needs an OKX API key).
3. **Live monetization (B/D/F)** — only after the wallet/payment risk review:
   Agentic Wallet identity, OKX Payment SDK verifier, A2A escrow deliverables.
