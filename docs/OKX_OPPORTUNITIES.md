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
| **C** | Analyze OKX / on-chain markets | pattern + microstructure + quant stack | consume `okx-dex-market` / `okx-dex-signal` | Expands TAM | Med | ⚠️ data-redistribution clause |
| **D** | A2A escrow deliverables | custom backtests, walk-forward of a user strategy, "red-team my strategy" (`red_team.py`) | A2A escrow on X Layer | Per-deliverable | Med | Med — needs wallet |
| **E** | Verifiable analysis | SHA-256 + Ed25519 audit chain | trust layer for disputes/Evaluators | Premium tier | Med | Low |
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

## Flagged upstream fix — Shield check-count drift

RUNECLAW reports its Shield check count inconsistently: **23** (the engine,
`risk_engine.py` / `skill_registry._TOTAL_RISK_CHECKS = 23`), **21** (the MCP tool
description in `bot/mcp/server.py`), and **18** (`getclaw_wrapper.py`). The engine
value (23) is authoritative. RUNECLAW is the pinned source of truth and is left
untouched here; a small RUNECLAW PR should reconcile the two stale strings to 23.
Our skill/docs reference the engine truth and note the served description still says
21 until that lands.

## Suggested next steps (in order)

1. **Reconcile the Shield count** upstream in RUNECLAW (small, correctness).
2. **Opportunity C — OKX data adapter** (read-only): let the analyzer/quant/Shield run
   on OKX DEX/CEX symbols, emitting *derived* signals only (respect the data clause).
3. **Opportunity E — signed attestation endpoint** surfacing the audit chain, for a
   "verifiable analysis" premium tier that fits the dispute/Evaluator economy.
4. **Live monetization (B/D/F)** — only after the wallet/payment risk review:
   Agentic Wallet identity, OKX Payment SDK verifier, A2A escrow deliverables.
