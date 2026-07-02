#!/usr/bin/env python3
"""
One-time OKX DEX API smoke test — run this ON the host whose IP is bound to the key.

Because an IP-bound OKX key only works from its bound IP, this check must run on your
server (not a laptop / CI / sandbox on a different IP). It reads credentials from the
environment (never hardcode secrets):

    export OKX_API_KEY=...  OKX_SECRET_KEY=...  OKX_PASSPHRASE=...  OKX_PROJECT=...
    python scripts/okx_dex_smoke.py                       # WETH on Ethereum, 4h
    python scripts/okx_dex_smoke.py --chain 501 --token <SOL token address>

It fetches a few OKX DEX candles and reports PASS/FAIL. On failure it prints the OKX
error code so the endpoint/version can be adjusted (OKX_DEX_API_BASE /
OKX_DEX_CANDLES_PATH). It never prints your secret — only the last 4 chars of the API
key, for sanity.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "vendor", "runeclaw")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


async def _run(args: argparse.Namespace) -> int:
    from runeclaw_okx.okx_dex import (
        OKX_DEX_API_BASE,
        OKX_DEX_CANDLES_PATH,
        OKXDexAuthError,
        OKXDexError,
        fetch_dex_candles,
        load_credentials,
    )

    print(f"[okx-dex-smoke] endpoint: {OKX_DEX_API_BASE}{OKX_DEX_CANDLES_PATH}")
    try:
        creds = load_credentials()
    except OKXDexAuthError as exc:
        print(f"FAIL (config): {exc}")
        return 2
    print(
        f"[okx-dex-smoke] using key ...{creds['key'][-4:]} | "
        f"passphrase set: {bool(creds['passphrase'])} | project set: {bool(creds['project'])}"
    )

    try:
        candles = await fetch_dex_candles(args.chain, args.token, args.bar, args.limit)
    except OKXDexError as exc:
        print(f"FAIL (OKX API): {exc}")
        print("  → auth/IP error? confirm this host's IP matches the key's bound IP.")
        print("  → endpoint/param error? set OKX_DEX_CANDLES_PATH / OKX_DEX_API_BASE to")
        print("    your OKX DEX API tier's candles endpoint, then re-run.")
        return 1
    except Exception as exc:  # noqa: BLE001 - diagnostic catch-all
        print(f"FAIL (network/other): {type(exc).__name__}: {exc}")
        return 1

    if not candles:
        print("FAIL: request succeeded but returned no candles (check chain/token).")
        return 1
    ascending = candles[0][0] < candles[-1][0] if len(candles) > 1 else True
    print(f"PASS — fetched {len(candles)} candles; ascending order: {ascending}")
    print("       DEX signing + endpoint are working. runeclaw_dex_quant is good to go.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", default="1", help="OKX chainIndex (default 1 = Ethereum).")
    ap.add_argument(
        "--token",
        default="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
        help="Token contract address (default WETH on Ethereum).",
    )
    ap.add_argument("--bar", default="4h", help="Candle timeframe (default 4h).")
    ap.add_argument("--limit", type=int, default=10, help="Number of candles (default 10).")
    return asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
