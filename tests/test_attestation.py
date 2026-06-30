"""
Tests for verifiable-analysis attestations (runeclaw_okx/attestation.py) and the
`runeclaw_attest_key` / `runeclaw_signed` tools.

Crypto round-trip, tamper detection, and catalogue invariant are pure (always run).
The dispatch tests need the RUNECLAW submodule and skip cleanly without it.
"""

from __future__ import annotations

import base64
import importlib.util
import json

import pytest

from runeclaw_okx import attestation as att

_HAS_RUNECLAW = importlib.util.find_spec("bot") is not None
_SEED_B64 = base64.b64encode(bytes(range(32))).decode()


# ---------------------------------------------------------------------------
# Canonicalisation + sign/verify (pure)
# ---------------------------------------------------------------------------

class TestAttestor:
    def test_canonical_is_order_independent(self):
        assert att.canonical_bytes({"b": 1, "a": 2}) == att.canonical_bytes({"a": 2, "b": 1})

    def test_attest_verify_round_trip(self):
        a = att.Attestor()
        payload = {"tool": "runeclaw_shield", "result": "APPROVED"}
        attestation = a.attest(payload)
        assert attestation["algo"] == "ed25519"
        assert att.verify_attestation(payload, attestation) is True

    def test_tamper_is_detected(self):
        a = att.Attestor()
        payload = {"result": "APPROVED"}
        attestation = a.attest(payload)
        assert att.verify_attestation({"result": "REJECTED"}, attestation) is False

    def test_wrong_key_fails_verification(self):
        payload = {"x": 1}
        attestation = att.Attestor().attest(payload)
        attestation = dict(attestation)
        attestation["public_key"] = att.Attestor().public_key_b64  # different key
        assert att.verify_attestation(payload, attestation) is False

    def test_from_env_seed_is_deterministic(self, monkeypatch):
        monkeypatch.setenv("MCP_ATTEST_PRIVATE_KEY", _SEED_B64)
        a, b = att.Attestor.from_env(), att.Attestor.from_env()
        assert a.key_id == b.key_id
        assert a.ephemeral is False

    def test_default_is_ephemeral(self, monkeypatch):
        monkeypatch.delenv("MCP_ATTEST_PRIVATE_KEY", raising=False)
        assert att.Attestor.from_env().ephemeral is True


class TestAttestCatalogue:
    def test_assert_attest_readonly_passes(self):
        att.assert_attest_readonly()

    def test_tool_names_non_executable(self):
        names = {t["mcp_name"] for t in att.ATTEST_TOOLS}
        assert names == {"runeclaw_attest_key", "runeclaw_signed"}
        assert not any("execute" in n for n in names)


# ---------------------------------------------------------------------------
# Dispatch through the extended server (needs the RUNECLAW submodule)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_RUNECLAW, reason="RUNECLAW submodule not importable")
class TestSignedTools:
    def _server(self, monkeypatch, token="att-token"):
        import bot.mcp.server as mcp_server

        monkeypatch.setenv("MCP_ATTEST_PRIVATE_KEY", _SEED_B64)
        att.reset_attestor(None)  # rebuild from env on next get_attestor()
        monkeypatch.setattr(mcp_server, "_MCP_AUTH_TOKEN", token)
        from runeclaw_okx.extended_server import build_extended_server

        return build_extended_server(), token

    def teardown_method(self):
        att.reset_attestor(None)

    def test_attest_key_returns_public_key(self, monkeypatch):
        import asyncio

        srv, token = self._server(monkeypatch)
        r = asyncio.run(srv.call_tool("runeclaw_attest_key", {}, auth_token=token))
        assert r["status"] == "success"
        info = json.loads(r["result"])
        assert info["algo"] == "ed25519" and info["public_key"]

    def test_signed_result_is_independently_verifiable(self, monkeypatch):
        import asyncio

        srv, token = self._server(monkeypatch)
        r = asyncio.run(
            srv.call_tool(
                "runeclaw_signed",
                {"tool": "runeclaw_macro_brief", "arguments": {}},
                auth_token=token,
            )
        )
        assert r["status"] == "success"
        payload = json.loads(r["result"])
        signed = {"request": payload["request"], "response": payload["response"]}
        assert att.verify_attestation(signed, payload["attestation"]) is True
        # Tampering with the signed result breaks verification.
        signed["response"]["result"] = "FORGED"
        assert att.verify_attestation(signed, payload["attestation"]) is False

    def test_signed_blocks_recursion_and_unknown(self, monkeypatch):
        import asyncio

        srv, token = self._server(monkeypatch)
        rec = asyncio.run(srv.call_tool("runeclaw_signed", {"tool": "runeclaw_signed"}, auth_token=token))
        unk = asyncio.run(srv.call_tool("runeclaw_signed", {"tool": "runeclaw_execute"}, auth_token=token))
        assert rec["status"] == "error" and unk["status"] == "error"

    def test_attest_tools_enforce_auth(self, monkeypatch):
        import asyncio

        srv, _ = self._server(monkeypatch)
        r = asyncio.run(srv.call_tool("runeclaw_attest_key", {}, auth_token="wrong"))
        assert r["status"] == "error" and "Authentication" in r["result"]
