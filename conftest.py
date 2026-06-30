"""
Pytest bootstrap for the RUNECLAW → OKX AI integration.

The transport adapter wraps RUNECLAW, which is pinned as a git submodule under
``vendor/runeclaw`` (the single source of truth — RUNECLAW is never duplicated or
modified here). Add that checkout to ``sys.path`` so ``import bot.mcp.server``
resolves to the submodule when it is initialised.

When the submodule is absent (e.g. a checkout without ``--recurse-submodules``),
nothing is added and the RUNECLAW-dependent tests skip via ``importorskip`` rather
than erroring — the standard-library-only security-guard tests still run.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNECLAW_ROOT = os.path.join(_HERE, "vendor", "runeclaw")

if os.path.isdir(os.path.join(_RUNECLAW_ROOT, "bot")) and _RUNECLAW_ROOT not in sys.path:
    sys.path.insert(0, _RUNECLAW_ROOT)
