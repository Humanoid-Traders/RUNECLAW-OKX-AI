"""
Seller-side pay-per-call payments for RUNECLAW → OKX AI (Opportunity B/live-monetization).

This is the **seller** half of an x402-style / OKX Agent-Payments-Protocol flow — the
only half a paid A2MCP provider actually owns, and the only half that needs neither a
private SDK nor the operator's wallet keys:

  1. An unpaid request gets an HTTP **402 Payment Required** with a machine-readable
     challenge (`accepts`: asset, amount, recipient, network, scheme, resource).
  2. The buyer's wallet settles on-chain via OKX's Broker and receives a **signed
     settlement receipt**.
  3. The buyer retries with the receipt in an `X-PAYMENT` header; this module
     **cryptographically verifies** it (Ed25519 over the canonical receipt) against the
     Broker's public key, checks recipient / asset / network / amount / expiry, and
     enforces single-use nonces (replay protection) before the call is served.

What stays OUTSIDE this code — by design, not omission:
  * the **buyer's wallet** and the **on-chain settlement** (OKX Broker),
  * the operator's **receiving wallet address** (config: ``OKX_PAY_RECIPIENT``),
  * the **Broker's receipt-signing public key** (config: ``OKX_PAY_BROKER_PUBKEY``).

So this module never holds funds, never signs a payment, and never touches a wallet —
it only *verifies* that a payment the operator's own wallet/Broker already settled is
valid. The exact OKX Broker receipt field names are an OKX-spec detail; the canonical
subset used here is env-/config-adjustable and should be confirmed against OKX's APP
spec before going live.

Off by default. Enabled only when ``MCP_REQUIRE_PAYMENT`` is set AND the config below
is present (fail-closed).
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from runeclaw_okx.attestation import canonical_bytes

_TRUTHY = {"1", "true", "yes", "on"}


class PaymentConfigError(RuntimeError):
    """Raised when paid mode is required but the payment config is incomplete."""


@dataclass(frozen=True)
class PaymentTerms:
    """What the buyer must pay, and to whom. Sourced from the environment."""

    recipient: str            # operator's receiving wallet address (OKX_PAY_RECIPIENT)
    broker_pubkey_b64: str    # Ed25519 pubkey the OKX Broker signs receipts with
    asset: str = "USDC"
    network: str = "xlayer"
    amount: str = "0.01"      # flat per-call price (string, minor-unit-safe)
    scheme: str = "exact"

    @classmethod
    def from_env(cls) -> "PaymentTerms":
        recipient = os.environ.get("OKX_PAY_RECIPIENT", "").strip()
        broker = os.environ.get("OKX_PAY_BROKER_PUBKEY", "").strip()
        missing = [n for n, v in (("OKX_PAY_RECIPIENT", recipient), ("OKX_PAY_BROKER_PUBKEY", broker)) if not v]
        if missing:
            raise PaymentConfigError(
                "Paid mode requires " + " and ".join(missing) + ". Set your receiving "
                "wallet address and the OKX Broker receipt-signing public key."
            )
        return cls(
            recipient=recipient,
            broker_pubkey_b64=broker,
            asset=os.environ.get("OKX_PAY_ASSET", "USDC").strip() or "USDC",
            network=os.environ.get("OKX_PAY_NETWORK", "xlayer").strip() or "xlayer",
            amount=os.environ.get("OKX_PAY_AMOUNT", "0.01").strip() or "0.01",
        )


def build_402_challenge(terms: PaymentTerms, resource: str) -> dict[str, Any]:
    """Build the x402-style payment-required challenge for a resource."""
    return {
        "x402Version": 1,
        "accepts": [
            {
                "scheme": terms.scheme,
                "network": terms.network,
                "asset": terms.asset,
                "amount": terms.amount,
                "payTo": terms.recipient,
                "resource": resource,
                "description": "RUNECLAW analysis — pay-per-call",
            }
        ],
    }


class NonceStore:
    """Single-use nonce tracker for replay protection.

    In-memory by default (fine for one process); back it with a shared store
    (e.g. Redis) for a multi-instance deployment.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def use(self, nonce: str) -> bool:
        """Return True if ``nonce`` was fresh (and record it); False if already used."""
        if not nonce or nonce in self._seen:
            return False
        self._seen.add(nonce)
        return True


def _decimal_ge(a: str, b: str) -> bool:
    """True if amount string ``a`` >= ``b`` (compared as floats; amounts are small)."""
    try:
        return float(a) >= float(b)
    except (TypeError, ValueError):
        return False


class SignedReceiptVerifier:
    """PaymentVerifier: accept a request only if it carries a valid Broker receipt.

    Duck-typed to the ``PaymentVerifier`` protocol in ``http_transport``.
    """

    def __init__(
        self,
        terms: PaymentTerms,
        nonce_store: NonceStore | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._terms = terms
        self._nonces = nonce_store or NonceStore()
        self._clock = clock
        self._broker_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(terms.broker_pubkey_b64))

    def challenge(self, resource: str) -> dict[str, Any]:
        return build_402_challenge(self._terms, resource)

    async def verify(self, *, path: str, headers: dict[bytes, bytes]) -> tuple[bool, str]:
        raw = headers.get(b"x-payment", b"")
        if not raw:
            return False, "Payment required: attach a settlement receipt in X-PAYMENT."
        try:
            envelope = json.loads(base64.b64decode(raw))
            payload = envelope["payload"]
            signature = base64.b64decode(envelope["signature"])
        except (ValueError, KeyError, TypeError):
            return False, "Malformed X-PAYMENT receipt."

        # 1) authenticity — Ed25519 over the canonical payload, from the Broker key.
        try:
            self._broker_key.verify(signature, canonical_bytes(payload))
        except InvalidSignature:
            return False, "Invalid payment receipt signature."

        # 2) the receipt must match our terms.
        t = self._terms
        if str(payload.get("payTo")) != t.recipient:
            return False, "Receipt recipient does not match this service."
        if str(payload.get("asset")) != t.asset or str(payload.get("network")) != t.network:
            return False, "Receipt asset/network does not match this service."
        if not _decimal_ge(str(payload.get("amount", "0")), t.amount):
            return False, "Receipt amount is below the required price."

        # 3) freshness + single use.
        try:
            if float(payload.get("expiry", 0)) < self._clock():
                return False, "Payment receipt has expired."
        except (TypeError, ValueError):
            return False, "Receipt has an invalid expiry."
        if not self._nonces.use(str(payload.get("nonce", ""))):
            return False, "Payment receipt already used (replay)."

        return True, ""

    @classmethod
    def from_env(cls) -> "SignedReceiptVerifier":
        return cls(PaymentTerms.from_env())


def payment_required_from_env() -> bool:
    return os.environ.get("MCP_REQUIRE_PAYMENT", "").strip().lower() in _TRUTHY
