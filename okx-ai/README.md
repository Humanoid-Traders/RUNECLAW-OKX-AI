# OKX AI — A2MCP registration artifacts (PR 4)

Registration-ready artifacts for listing RUNECLAW's read-only analysis on OKX AI as
an **ASP → Agent-to-MCP (A2MCP)** provider: a service **called directly via MCP**,
**fixed price per call**, **settled via the OKX Payment SDK**.

> **Repo-side only — no wallet, no live registration.** These files describe and
> prepare the service. They do **not** create an Agentic Wallet, connect payment, or
> register anything on OKX. The actual registration (wallet email-login + ASP
> registration) is a separate, financially consequential step the operator runs on
> their own OKX-connected agent — see "Registering" below.

## Files

| File | What it is |
|---|---|
| [`manifest.json`](manifest.json) | The A2MCP service descriptor: name, endpoint, per-call pricing, and the nine read-only tools with their JSON Schemas. |
| [`../scripts/generate_a2mcp_manifest.py`](../scripts/generate_a2mcp_manifest.py) | Regenerates `manifest.json` from RUNECLAW's live `TOOL_CATALOGUE`, so it can't drift (and can't list an execution tool — there are none). |

Regenerate / verify:

```bash
PYTHONPATH=vendor/runeclaw python scripts/generate_a2mcp_manifest.py          # write
PYTHONPATH=vendor/runeclaw python scripts/generate_a2mcp_manifest.py --check  # CI: fail if stale
```

Before listing, fill the placeholders in `manifest.json` (`provider.*`,
`endpoint.url`) and review per-call prices in the generator.

## Pay-per-call (x402 seller gate)

The HTTP transport implements the **seller side** of an x402 / OKX Agent-Payments
flow (`runeclaw_okx/payments.py`, `runeclaw_okx/http_transport.py`). **Off by
default** — the endpoint is byte-identical to the free transport unless enabled.

**How it works**

1. An unpaid request to `/mcp` gets **HTTP 402** with a machine-readable x402
   challenge (`accepts`: `scheme`, `network`, `asset`, `amount`, `payTo`, `resource`).
2. The buyer's wallet settles on-chain via **OKX's Broker** and receives a **signed
   settlement receipt**.
3. The buyer retries with the receipt in an `X-PAYMENT` header. `SignedReceiptVerifier`
   **Ed25519-verifies** it against the Broker's public key and checks
   recipient / asset / network / amount / expiry and a **single-use nonce** (replay
   protection) before the call is served. Payment runs **after** bearer-auth.

**Enable it** (fail-closed — refuses to serve for free if config is incomplete):

```bash
export MCP_REQUIRE_PAYMENT=1
export OKX_PAY_RECIPIENT="<your receiving wallet address>"
export OKX_PAY_BROKER_PUBKEY="<OKX Broker receipt-signing Ed25519 pubkey, base64>"
export OKX_PAY_ASSET=USDC OKX_PAY_NETWORK=xlayer OKX_PAY_AMOUNT=0.01   # optional
python -m runeclaw_okx.transport --transport http
```

**What this code does NOT do (by design):** it never holds funds, signs a payment, or
touches a wallet — it only *verifies* a receipt your own wallet/Broker already
settled. The buyer's wallet and the on-chain settlement live in OKX's Broker.

**Confirm before going live:** the OKX Broker's exact receipt field names / signing
key and whether OKX's "Payment SDK" imposes a different envelope are an OKX-spec
detail (not machine-readable from OKX's public docs). The canonical receipt subset
used here is standard x402; verify it against OKX's APP spec, and note that operating
a paid listing (a receiving wallet + on-chain settlement) is the **wallet/payment
surface** the integration plan reserved for a risk review (§5/§7).

## Registering (operator runs this — not automated here)

Per OKX AI's flow, registration is agent-driven on an OKX-connected agent
(OpenClaw / Hermes / Claude Code with `okx/onchainos-skills` installed):

1. `npx skills add okx/onchainos-skills --yes -g`, then log in to the Agentic Wallet.
2. Register the ASP as **A2MCP** (not A2A — A2A is for negotiated complex tasks).
   Provide the name, description, tool/service list, and per-call pricing from
   `manifest.json`, and point the endpoint at your deployed `…/mcp` URL.

## Open items — confirm against OKX's ASP spec before listing

The exact provider-side schema isn't in OKX's public docs, so the manifest layout
here is a **draft** (`_schema: okx-ai/a2mcp@draft`). Confirm:

- required **frontmatter/manifest fields** beyond those modelled here (identity,
  category, versioning, an explicit per-tool vs flat pricing shape);
- the **submission path** (an OKX registry, a PR, or the agent-driven flow above);
- whether listing **requires an Agentic Wallet / on-chain identity** even for this
  service, and the **OKX Payment SDK** package + its proof/settlement header — these
  cross the integration plan's "no wallet surface" line (§5/§7) and need an explicit
  risk review before going live.
