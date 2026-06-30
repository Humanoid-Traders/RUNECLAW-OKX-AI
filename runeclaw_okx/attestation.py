"""
Verifiable analysis — Ed25519 attestations for RUNECLAW → OKX AI (Opportunity E).

In a trustless agent economy (OKX AI's disputes / OKB-staked Evaluators), being
able to *prove* "RUNECLAW returned exactly this, unaltered" is a real edge. This
module signs analysis payloads with Ed25519 — the same primitive RUNECLAW's
audit-chain attestation uses — but as a standalone, **externally verifiable**
receipt: the signature is over the canonical JSON bytes, so any Ed25519 library can
verify it given the public key (no RUNECLAW code required).

It exposes two read-only MCP tools (wired in extended_server):
  * ``runeclaw_attest_key`` — fetch the server's attestation public key + recipe.
  * ``runeclaw_signed``     — run any read-only tool and get its result plus a
                              signature over ``{request, response}``.

The signing key comes from ``MCP_ATTEST_PRIVATE_KEY`` (base64 of a 32-byte Ed25519
seed) for a persistent identity, or is generated ephemerally per process if unset.
Read-only and analysis-only: signing never places or mutates anything.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

ALGO = "ed25519"
_HASH = "sha256"


def canonical_bytes(payload: Any) -> bytes:
    """Deterministic JSON encoding used for both signing and verification."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def _key_id(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).hexdigest()[:16]


class Attestor:
    """Holds an Ed25519 key and produces / verifies analysis attestations."""

    def __init__(self, private_key: Ed25519PrivateKey | None = None, ephemeral: bool = False) -> None:
        self._key = private_key or Ed25519PrivateKey.generate()
        self.ephemeral = ephemeral
        self._public_raw = self._key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )

    @classmethod
    def from_env(cls) -> "Attestor":
        """Build from ``MCP_ATTEST_PRIVATE_KEY`` (base64 32-byte seed), else ephemeral."""
        seed_b64 = os.environ.get("MCP_ATTEST_PRIVATE_KEY", "").strip()
        if seed_b64:
            seed = base64.b64decode(seed_b64)
            return cls(Ed25519PrivateKey.from_private_bytes(seed), ephemeral=False)
        return cls(ephemeral=True)

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self._public_raw).decode()

    @property
    def key_id(self) -> str:
        return _key_id(self._public_raw)

    def attest(self, payload: Any) -> dict[str, Any]:
        """Return a self-describing, externally verifiable attestation over ``payload``."""
        msg = canonical_bytes(payload)
        return {
            "algo": ALGO,
            "hash": _HASH,
            "key_id": self.key_id,
            "public_key": self.public_key_b64,
            "content_sha256": hashlib.sha256(msg).hexdigest(),
            "signature": base64.b64encode(self._key.sign(msg)).decode(),
        }

    def key_info(self) -> dict[str, Any]:
        return {
            "algo": ALGO,
            "hash": _HASH,
            "key_id": self.key_id,
            "public_key": self.public_key_b64,
            "ephemeral": self.ephemeral,
            "verify_recipe": (
                "Reconstruct the signed payload, canonicalize as compact JSON with "
                "sorted keys (UTF-8), then Ed25519-verify `signature` (base64) against "
                "those bytes using `public_key` (base64, raw 32-byte). `content_sha256` "
                "is sha256 of the same bytes."
            ),
        }


def verify_attestation(payload: Any, attestation: dict[str, Any]) -> bool:
    """Verify an attestation against a payload using only the attestation's public key.

    Pure / dependency-light so any consumer (or an Evaluator) can run it.
    """
    try:
        msg = canonical_bytes(payload)
        if attestation.get("content_sha256") != hashlib.sha256(msg).hexdigest():
            return False
        public_raw = base64.b64decode(attestation["public_key"])
        signature = base64.b64decode(attestation["signature"])
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, msg)
        return True
    except (InvalidSignature, KeyError, ValueError, TypeError):
        return False


# Process-wide attestor (stable key within a server process).
_ATTESTOR: Attestor | None = None


def get_attestor() -> Attestor:
    global _ATTESTOR
    if _ATTESTOR is None:
        _ATTESTOR = Attestor.from_env()
    return _ATTESTOR


def reset_attestor(attestor: Attestor | None = None) -> None:
    """Test hook: replace/clear the process attestor."""
    global _ATTESTOR
    _ATTESTOR = attestor


# Pure-data tool catalogue for the attestation meta-tools.
ATTEST_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "mcp_name": "runeclaw_attest_key",
        "description": (
            "Return the server's Ed25519 attestation public key, key id, and the "
            "verification recipe, so callers can independently verify signed analysis. "
            "Read-only."
        ),
        "params": (),
    },
    {
        "mcp_name": "runeclaw_signed",
        "description": (
            "Run any read-only analysis tool and return its result together with an "
            "Ed25519 signature over {request, response} — a portable, independently "
            "verifiable receipt that RUNECLAW produced exactly this output. Read-only."
        ),
        "params": (
            {
                "name": "tool",
                "type": "string",
                "description": "The read-only tool to run, e.g. 'runeclaw_shield'.",
                "required": True,
            },
            {
                "name": "arguments",
                "type": "object",
                "description": "Arguments object for the inner tool (optional).",
                "required": False,
            },
        ),
    },
)

ATTEST_TOOL_NAMES: frozenset[str] = frozenset(t["mcp_name"] for t in ATTEST_TOOLS)


def assert_attest_readonly() -> None:
    """Fail closed if an attestation tool name ever looks executable."""
    for t in ATTEST_TOOLS:
        if "execute" in t["mcp_name"].lower():
            raise RuntimeError(f"Attestation tool name looks executable: {t['mcp_name']}")
