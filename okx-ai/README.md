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

## Payment integration (OKX Payment SDK)

The HTTP transport has a single, **off-by-default** seam for pay-per-call
settlement (`runeclaw_okx/http_transport.py`):

- `PaymentVerifier` — a `Protocol` a real OKX Payment SDK adapter implements
  (`verify(path, headers) -> (paid, reason)`).
- `PaymentASGIMiddleware` — enforces it, returning **HTTP 402** when unpaid. It runs
  **after** bearer-auth, so callers are authenticated before they are charged.
- `MCP_REQUIRE_PAYMENT` — when set, the app **fails closed**: it refuses to build
  unless a `PaymentVerifier` is wired, so a paid listing can never serve for free.

By default payment is disabled and the endpoint behaves exactly like the free
transport. Plug the SDK in by passing `build_http_app(payment_verifier=...)`.

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
