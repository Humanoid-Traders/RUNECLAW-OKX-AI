# RUNECLAW skill pack (for OKX AI / Onchain OS)

Markdown+YAML **skills** that front RUNECLAW's read-only analysis on the OKX AI /
Onchain OS marketplace, so agents (OpenClaw, Hermes, Claude Code, Codex) can
discover and use them in natural language. This implements **PR 5** of
[`../vendor/runeclaw/docs/OKX_AI_MCP_INTEGRATION.md`](../vendor/runeclaw/docs/OKX_AI_MCP_INTEGRATION.md).

| Skill | Fronts MCP tool | What it does |
|---|---|---|
| [`runeclaw-shield`](runeclaw-shield/SKILL.md) | `runeclaw_shield` | Fail-closed pre-trade risk checks (23 in-engine) → approved/rejected verdict |
| [`runeclaw-analyze`](runeclaw-analyze/SKILL.md) | `runeclaw_analyze` | Turn a symbol into a structured trade idea |
| [`runeclaw-quant`](runeclaw-quant/SKILL.md) | `runeclaw_quant` | Regime / GARCH vol / Hurst / edge-gate quant report |

These front the **analysis**, not Bitget execution. Each skill is read-only and
points the agent at the RUNECLAW MCP server (the stdio / streamable-HTTP transports
in this repo) — there is no execution path.

## Format

Each skill is a directory containing a `SKILL.md` with YAML frontmatter
(`name`, `description` — kept to ≤1024 characters) followed by Markdown
instructions, matching the open *agent-skills* format that OKX's `npx skills add`
tooling consumes. `tests/test_skills.py` validates the frontmatter and asserts the
skills reference only read-only MCP tools (no execution).

## Distribution

OKX AI agents install skill packs with, e.g.:

```bash
npx skills add okx/onchainos-skills --yes -g
```

To make this pack installable the same way, it needs to be published to a skills
registry namespace (e.g. a public repo the `skills` CLI can resolve) or submitted
to OKX's `okx/agent-skills` collection.

## Assumptions / open items

The publicly documented agent-installation flow shows skills installed via
`npx skills add okx/<pack>`, and confirms the Markdown+YAML skill shape, but does
**not** publish the exact provider-side submission schema. Before listing, confirm
against OKX's skill-authoring / ASP spec:

- any **additional required frontmatter fields** (beyond `name` / `description`) —
  e.g. version, author, category, pricing, or an MCP-server binding block;
- the **submission path** (PR to `okx/agent-skills`, an npm package name, or a repo
  the `skills` CLI resolves), and any review/verification step;
- whether listing requires an **OKX Agentic Wallet / on-chain identity** even for a
  free, read-only pack — this crosses the plan's "no wallet surface" line (§5/§7)
  and needs an explicit decision before going live.
