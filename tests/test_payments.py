"""
Tests for the seller-side pay-per-call payment gate (runeclaw_okx/payments.py).

All pure/deterministic — real Ed25519 crypto with a test Broker key, no network and
no wallet. Covers a valid receipt plus every rejection path, fail-closed config, and
the x402 402 challenge through the ASGI middleware.
"""

from __future__ import annotations

import base64
import importlib.util
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runeclaw_okx import payments as pay
from runeclaw_okx.attestation import canonical_bytes

_HAS_STARLETTE = importlib.util.find_spec("starlette") is not None

# A stand-in "OKX Broker" signing key for tests.
_BROKER = Ed25519PrivateKey.generate()
_BROKER_PUB_B64 = base64.b64encode(
    _BROKER.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
).decode()

_TERMS = pay.PaymentTerms(
    recipient="0xRECIPIENT",
    broker_pubkey_b64=_BROKER_PUB_B64,
    asset="USDC",
    network="xlayer",
    amount="0.01",
)


def _receipt_header(_signer=None, **overrides) -> bytes:
    payload = {
        "payTo": "0xRECIPIENT",
        "asset": "USDC",
        "network": "xlayer",
        "amount": "0.01",
        "nonce": "n-1",
        "expiry": 10_000.0,
        **overrides,
    }
    signer = _signer or _BROKER
    signature = base64.b64encode(signer.sign(canonical_bytes(payload))).decode()
    envelope = {"payload": payload, "signature": signature}
    return base64.b64encode(json.dumps(envelope).encode())


def _verify(header: bytes | None, clock_now: float = 0.0):
    import asyncio

    v = pay.SignedReceiptVerifier(_TERMS, clock=lambda: clock_now)
    headers = {b"x-payment": header} if header is not None else {}
    return asyncio.run(v.verify(path="/mcp/", headers=headers)), v


class TestReceiptVerification:
    def test_valid_receipt_is_accepted(self):
        (ok, reason), _ = _verify(_receipt_header())
        assert ok is True and reason == ""

    def test_missing_receipt_is_402_reason(self):
        (ok, reason), _ = _verify(None)
        assert ok is False and "Payment required" in reason

    def test_bad_signature_rejected(self):
        forged = Ed25519PrivateKey.generate()
        (ok, reason), _ = _verify(_receipt_header(_signer=forged))
        assert ok is False and "signature" in reason.lower()

    def test_wrong_recipient_rejected(self):
        (ok, reason), _ = _verify(_receipt_header(payTo="0xATTACKER"))
        assert ok is False and "recipient" in reason.lower()

    def test_wrong_asset_rejected(self):
        (ok, reason), _ = _verify(_receipt_header(asset="DOGE"))
        assert ok is False and "asset" in reason.lower()

    def test_insufficient_amount_rejected(self):
        (ok, reason), _ = _verify(_receipt_header(amount="0.001"))
        assert ok is False and "below" in reason.lower()

    def test_expired_receipt_rejected(self):
        (ok, reason), _ = _verify(_receipt_header(expiry=100.0), clock_now=200.0)
        assert ok is False and "expired" in reason.lower()

    def test_replayed_nonce_rejected(self):
        import asyncio

        v = pay.SignedReceiptVerifier(_TERMS, clock=lambda: 0.0)
        h = {b"x-payment": _receipt_header(nonce="once")}
        first = asyncio.run(v.verify(path="/mcp/", headers=h))
        second = asyncio.run(v.verify(path="/mcp/", headers=h))
        assert first[0] is True
        assert second[0] is False and "replay" in second[1].lower()

    def test_malformed_header_rejected(self):
        (ok, reason), _ = _verify(b"not-base64-json!!")
        assert ok is False and "malformed" in reason.lower()


class TestPaymentConfig:
    def test_terms_from_env_fail_closed(self, monkeypatch):
        monkeypatch.delenv("OKX_PAY_RECIPIENT", raising=False)
        monkeypatch.delenv("OKX_PAY_BROKER_PUBKEY", raising=False)
        with pytest.raises(pay.PaymentConfigError, match="OKX_PAY_RECIPIENT"):
            pay.PaymentTerms.from_env()

    def test_terms_from_env(self, monkeypatch):
        monkeypatch.setenv("OKX_PAY_RECIPIENT", "0xabc")
        monkeypatch.setenv("OKX_PAY_BROKER_PUBKEY", _BROKER_PUB_B64)
        monkeypatch.setenv("OKX_PAY_ASSET", "USDT")
        t = pay.PaymentTerms.from_env()
        assert t.recipient == "0xabc" and t.asset == "USDT"

    def test_challenge_shape(self):
        v = pay.SignedReceiptVerifier(_TERMS)
        ch = v.challenge("/mcp/")
        assert ch["x402Version"] == 1
        acc = ch["accepts"][0]
        assert acc["payTo"] == "0xRECIPIENT" and acc["asset"] == "USDC" and acc["amount"] == "0.01"


# ---------------------------------------------------------------------------
# Integration through the payment middleware (402 with x402 challenge)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_STARLETTE, reason="starlette not installed")
class TestPaymentMiddlewareX402:
    def _client(self):
        from starlette.applications import Starlette
        from starlette.routing import Mount
        from starlette.testclient import TestClient

        from runeclaw_okx.http_transport import PaymentASGIMiddleware

        async def _ok(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"served"})

        verifier = pay.SignedReceiptVerifier(_TERMS, clock=lambda: 0.0)
        app = Starlette(routes=[Mount("/mcp", app=PaymentASGIMiddleware(_ok, verifier))])
        return TestClient(app)

    def test_unpaid_gets_402_with_x402_challenge(self):
        r = self._client().get("/mcp/")
        assert r.status_code == 402
        body = r.json()
        assert body["x402Version"] == 1
        assert body["accepts"][0]["payTo"] == "0xRECIPIENT"

    def test_valid_receipt_is_served(self):
        r = self._client().get(
            "/mcp/", headers={"X-PAYMENT": _receipt_header(nonce="mw-1").decode()}
        )
        assert r.status_code == 200
        assert r.text == "served"
