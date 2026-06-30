"""
Tests for the streamable-HTTP MCP transport (runeclaw_okx/http_transport.py).

Layered availability, like the stdio tests:
  * the rate-limiter tests are pure (stdlib only) and always run;
  * the ASGI bearer-auth / rate-limit middleware tests need Starlette (installed
    with the `mcp` SDK) and skip otherwise;
  * the full-app integration tests additionally need the RUNECLAW submodule.
"""

from __future__ import annotations

import importlib.util

import pytest

from runeclaw_okx import http_transport
from runeclaw_okx.http_transport import (
    BearerAuthASGIMiddleware,
    PaymentASGIMiddleware,
    RateLimiter,
)

_HAS_MCP_SDK = importlib.util.find_spec("mcp") is not None
_HAS_STARLETTE = importlib.util.find_spec("starlette") is not None


class _FakeClock:
    """Deterministic monotonic clock for rate-limit tests."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ---------------------------------------------------------------------------
# RateLimiter (pure)
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_allows_up_to_limit_then_denies(self):
        clock = _FakeClock()
        rl = RateLimiter(limit=3, window_seconds=60, clock=clock)
        assert [rl.check("k")[0] for _ in range(3)] == [True, True, True]
        allowed, retry_after = rl.check("k")
        assert allowed is False
        assert retry_after >= 1

    def test_window_resets_after_elapsed(self):
        clock = _FakeClock()
        rl = RateLimiter(limit=1, window_seconds=60, clock=clock)
        assert rl.check("k")[0] is True
        assert rl.check("k")[0] is False
        clock.advance(60)
        assert rl.check("k")[0] is True  # new window

    def test_limits_are_per_key(self):
        clock = _FakeClock()
        rl = RateLimiter(limit=1, window_seconds=60, clock=clock)
        assert rl.check("token-a")[0] is True
        assert rl.check("token-b")[0] is True  # different key unaffected
        assert rl.check("token-a")[0] is False


# ---------------------------------------------------------------------------
# Bearer-auth + rate-limit ASGI middleware
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_STARLETTE, reason="starlette not installed")
class TestBearerAuthMiddleware:
    def _client(self, token="secret", limit=100):
        from starlette.applications import Starlette
        from starlette.routing import Mount
        from starlette.testclient import TestClient

        async def _ok(scope, receive, send):
            await send(
                {"type": "http.response.start", "status": 200, "headers": []}
            )
            await send({"type": "http.response.body", "body": b"ok"})

        limiter = RateLimiter(limit=limit, window_seconds=60, clock=_FakeClock())
        guarded = BearerAuthASGIMiddleware(_ok, token, limiter)
        app = Starlette(routes=[Mount("/mcp", app=guarded)])
        return TestClient(app)

    def test_missing_token_is_401(self):
        assert self._client().get("/mcp/").status_code == 401

    def test_wrong_token_is_401(self):
        r = self._client(token="secret").get(
            "/mcp/", headers={"Authorization": "Bearer nope"}
        )
        assert r.status_code == 401

    def test_correct_token_passes_through(self):
        r = self._client(token="secret").get(
            "/mcp/", headers={"Authorization": "Bearer secret"}
        )
        assert r.status_code == 200
        assert r.text == "ok"

    def test_rate_limit_returns_429_with_retry_after(self):
        client = self._client(token="secret", limit=2)
        hdr = {"Authorization": "Bearer secret"}
        assert client.get("/mcp/", headers=hdr).status_code == 200
        assert client.get("/mcp/", headers=hdr).status_code == 200
        r = client.get("/mcp/", headers=hdr)
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) >= 1


# ---------------------------------------------------------------------------
# OKX Payment SDK scaffold (pay-per-call gate) — off by default
# ---------------------------------------------------------------------------

class _FakeVerifier:
    def __init__(self, paid: bool, reason: str = "") -> None:
        self.paid = paid
        self.reason = reason
        self.calls = 0

    async def verify(self, *, path, headers):
        self.calls += 1
        return self.paid, self.reason


@pytest.mark.skipif(not _HAS_STARLETTE, reason="starlette not installed")
class TestPaymentMiddleware:
    def _client(self, verifier):
        from starlette.applications import Starlette
        from starlette.routing import Mount
        from starlette.testclient import TestClient

        async def _ok(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app = Starlette(routes=[Mount("/mcp", app=PaymentASGIMiddleware(_ok, verifier))])
        return TestClient(app)

    def test_unpaid_returns_402(self):
        v = _FakeVerifier(paid=False, reason="no settlement proof")
        r = self._client(v).get("/mcp/")
        assert r.status_code == 402
        assert "no settlement proof" in r.json()["result"]

    def test_paid_passes_through(self):
        r = self._client(_FakeVerifier(paid=True)).get("/mcp/")
        assert r.status_code == 200
        assert r.text == "ok"


class TestPaymentDefault:
    def test_payment_off_by_default(self, monkeypatch):
        monkeypatch.delenv("MCP_REQUIRE_PAYMENT", raising=False)
        assert http_transport._payment_required_default() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
    def test_env_enables_requirement(self, monkeypatch, value):
        monkeypatch.setenv("MCP_REQUIRE_PAYMENT", value)
        assert http_transport._payment_required_default() is True


# ---------------------------------------------------------------------------
# Full-app guards (need the mcp SDK; guard failures raise before RUNECLAW load)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_MCP_SDK, reason="official `mcp` SDK not installed")
class TestHttpAppGuards:
    def test_build_refuses_without_token(self, monkeypatch):
        monkeypatch.delenv("MCP_ALLOW_EXECUTE", raising=False)
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN"):
            http_transport.build_http_app()

    def test_build_refuses_when_execute_enabled(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_EXECUTE", "true")
        monkeypatch.setenv("MCP_AUTH_TOKEN", "secret")
        with pytest.raises(RuntimeError, match="MCP_ALLOW_EXECUTE"):
            http_transport.build_http_app()

    def test_build_refuses_when_payment_required_without_verifier(self, monkeypatch):
        # Fail-closed: don't serve a paid A2MCP listing for free.
        monkeypatch.delenv("MCP_ALLOW_EXECUTE", raising=False)
        monkeypatch.setenv("MCP_AUTH_TOKEN", "secret")
        monkeypatch.setenv("MCP_REQUIRE_PAYMENT", "true")
        with pytest.raises(RuntimeError, match="PaymentVerifier"):
            http_transport.build_http_app()


# ---------------------------------------------------------------------------
# Full-app integration (need the mcp SDK AND the RUNECLAW submodule)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_MCP_SDK, reason="official `mcp` SDK not installed")
class TestHttpAppIntegration:
    def _client(self, monkeypatch, token="test-token"):
        pytest.importorskip("bot.mcp.server")  # skip if submodule absent
        import bot.mcp.server as mcp_server
        from starlette.testclient import TestClient

        monkeypatch.delenv("MCP_ALLOW_EXECUTE", raising=False)
        monkeypatch.setenv("MCP_AUTH_TOKEN", token)
        monkeypatch.setattr(mcp_server, "_MCP_AUTH_TOKEN", token)
        app = http_transport.build_http_app()
        return TestClient(app)

    def test_healthz_is_unauthenticated(self, monkeypatch):
        with self._client(monkeypatch) as client:
            r = client.get("/healthz")
            assert r.status_code == 200
            assert r.json()["status"] == "ok"

    def test_mcp_endpoint_requires_auth(self, monkeypatch):
        with self._client(monkeypatch) as client:
            # No Authorization header → rejected by the middleware before MCP.
            r = client.post("/mcp/", json={"jsonrpc": "2.0", "method": "ping", "id": 1})
            assert r.status_code == 401

    def test_valid_token_gets_past_auth(self, monkeypatch):
        with self._client(monkeypatch, token="test-token") as client:
            r = client.post(
                "/mcp/",
                headers={
                    "Authorization": "Bearer test-token",
                    "Accept": "application/json, text/event-stream",
                },
                json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            )
            # Past the auth gate: whatever the MCP layer answers, it is not a 401.
            assert r.status_code != 401

    def test_payment_gate_runs_after_auth(self, monkeypatch):
        # Wiring order: a valid token clears auth, then a denying verifier → 402.
        pytest.importorskip("bot.mcp.server")
        import bot.mcp.server as mcp_server
        from starlette.testclient import TestClient

        monkeypatch.delenv("MCP_ALLOW_EXECUTE", raising=False)
        monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
        monkeypatch.setattr(mcp_server, "_MCP_AUTH_TOKEN", "test-token")
        verifier = _FakeVerifier(paid=False, reason="unpaid")
        app = http_transport.build_http_app(payment_verifier=verifier, require_payment=True)
        with TestClient(app) as client:
            # No token → 401 (auth first), verifier never consulted.
            assert client.post("/mcp/", json={}).status_code == 401
            assert verifier.calls == 0
            # Valid token → auth clears, payment gate denies → 402.
            r = client.post("/mcp/", headers={"Authorization": "Bearer test-token"}, json={})
            assert r.status_code == 402
            assert verifier.calls == 1
