"""
RUNECLAW → OKX AI: analysis-only MCP **streamable-HTTP** transport.

PR 3 of ``vendor/runeclaw/docs/OKX_AI_MCP_INTEGRATION.md``: a network-reachable
endpoint for hosts (like OKX AI's A2MCP pay-per-call model) that need HTTP rather
than stdio. It reuses the exact same read-only adapter as the stdio transport
(:func:`runeclaw_okx.transport.build_server`) — same catalogue, same four
analysis-only enforcement layers — and adds an HTTP front door:

* **Bind localhost by default** (`127.0.0.1`). A public deployment terminates TLS
  at a reverse proxy in front of this; see the README runbook.
* **DNS-rebinding protection** via the SDK's ``TransportSecuritySettings``
  (allowed hosts/origins), configurable through the environment.
* **Bearer auth on every request** — `Authorization: Bearer <MCP_AUTH_TOKEN>`,
  hmac-compared, fail-closed (401 on missing/bad token). Unlike stdio, HTTP can
  carry a per-request token, so this is the real auth boundary; the same token is
  forwarded into RUNECLAW's in-process check (defence in depth).
* **Per-token rate limiting** — a fixed-window limiter (429 + ``Retry-After`` when
  exceeded), keyed per token so a dedicated OKX token can't exhaust the service.

The auth/rate-limit layer is a *pure ASGI* middleware (not ``BaseHTTPMiddleware``)
so it never buffers the MCP streamable-HTTP/SSE response.

Run::

    MCP_AUTH_TOKEN=... python -m runeclaw_okx.transport --transport http --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import time
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from runeclaw_okx.transport import _TRUTHY, _resolve_auth_token, build_server

# Default fixed-window rate limit (requests per window, per token).
_DEFAULT_RPM = 120
_RATE_WINDOW_SECONDS = 60.0

# Default localhost bind + the host header allow-list that pairs with it.
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765

Clock = Callable[[], float]
ASGIApp = Callable[[dict, Callable, Callable], Awaitable[None]]


class RateLimiter:
    """Fixed-window, per-key request limiter.

    Pure and deterministic: the clock is injectable so tests don't depend on wall
    time. ``check(key)`` records a hit and returns ``(allowed, retry_after)``.
    """

    def __init__(
        self,
        limit: int = _DEFAULT_RPM,
        window_seconds: float = _RATE_WINDOW_SECONDS,
        clock: Clock = time.monotonic,
    ) -> None:
        self._limit = max(1, limit)
        self._window = window_seconds
        self._clock = clock
        self._state: dict[str, tuple[float, int]] = {}  # key -> (window_start, count)

    def check(self, key: str) -> tuple[bool, int]:
        now = self._clock()
        start, count = self._state.get(key, (now, 0))
        if now - start >= self._window:
            # window elapsed → reset
            start, count = now, 0
        if count >= self._limit:
            retry_after = max(1, int(self._window - (now - start)) + 1)
            return False, retry_after
        self._state[key] = (start, count + 1)
        return True, 0


class BearerAuthASGIMiddleware:
    """Pure-ASGI bearer-token gate + per-token rate limit in front of the MCP app.

    Short-circuits with 401 (missing/invalid token) or 429 (rate limited) before
    the request ever reaches the MCP handler; otherwise passes through untouched
    so streaming responses are not buffered.
    """

    def __init__(self, app: ASGIApp, token: str, limiter: RateLimiter) -> None:
        self._app = app
        self._token = token
        self._limiter = limiter

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        raw = headers.get(b"authorization", b"").decode("latin-1")
        presented = raw[7:].strip() if raw[:7].lower() == "bearer " else ""

        if not presented or not hmac.compare_digest(presented, self._token):
            await self._reject(send, 401, "Unauthorized: provide a valid Bearer token.")
            return

        allowed, retry_after = self._limiter.check(presented)
        if not allowed:
            await self._reject(
                send, 429, "Rate limit exceeded.", retry_after=retry_after
            )
            return

        await self._app(scope, receive, send)

    @staticmethod
    async def _reject(
        send: Callable, status: int, message: str, retry_after: int | None = None
    ) -> None:
        body = json.dumps({"status": "error", "result": message}).encode()
        headers = [(b"content-type", b"application/json")]
        if retry_after is not None:
            headers.append((b"retry-after", str(retry_after).encode()))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


@runtime_checkable
class PaymentVerifier(Protocol):
    """Integration seam for OKX A2MCP pay-per-call settlement (OKX Payment SDK).

    A real implementation wraps the OKX Payment SDK: it inspects the request's
    payment proof (e.g. a settlement header the calling agent attaches) and
    confirms the per-call charge cleared. RUNECLAW ships no concrete verifier —
    the analysis service runs free/unmetered by default — so this is the single
    place to plug the SDK in when listing as a paid A2MCP provider.
    """

    async def verify(self, *, path: str, headers: dict[bytes, bytes]) -> tuple[bool, str]:
        """Return ``(paid, reason)``. ``reason`` is surfaced on a 402 when unpaid."""
        ...


class PaymentASGIMiddleware:
    """Pure-ASGI per-call payment gate (HTTP 402 when unpaid).

    Sits between auth and the MCP handler — callers are authenticated *before*
    they are charged. Off by default: only inserted when a :class:`PaymentVerifier`
    is configured (see :func:`build_http_app`).
    """

    def __init__(self, app: ASGIApp, verifier: PaymentVerifier) -> None:
        self._app = app
        self._verifier = verifier

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        path = scope.get("path", "")
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        paid, reason = await self._verifier.verify(path=path, headers=headers)
        if not paid:
            payload: dict[str, Any] = {"status": "error", "result": reason or "Payment required."}
            # Attach the x402 payment challenge when the verifier can describe terms.
            challenge = getattr(self._verifier, "challenge", None)
            if callable(challenge):
                payload.update(challenge(path))
            await send(
                {
                    "type": "http.response.start",
                    "status": 402,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": json.dumps(payload).encode()})
            return
        await self._app(scope, receive, send)


def _payment_required_default() -> bool:
    return os.environ.get("MCP_REQUIRE_PAYMENT", "").strip().lower() in _TRUTHY


def _security_settings() -> Any:
    """Build DNS-rebinding protection settings (localhost allow-list by default)."""
    from mcp.server.transport_security import TransportSecuritySettings

    hosts_env = os.environ.get("MCP_HTTP_ALLOWED_HOSTS", "").strip()
    origins_env = os.environ.get("MCP_HTTP_ALLOWED_ORIGINS", "").strip()
    allowed_hosts = (
        [h.strip() for h in hosts_env.split(",") if h.strip()]
        if hosts_env
        else ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"]
    )
    allowed_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def build_http_app(
    rc_server: Any | None = None,
    *,
    requests_per_minute: int = _DEFAULT_RPM,
    mount_path: str = "/mcp",
    payment_verifier: PaymentVerifier | None = None,
    require_payment: bool | None = None,
) -> Any:
    """Build the Starlette ASGI app exposing the analysis-only MCP server over HTTP.

    Enforces the same fail-closed guards as stdio (via :func:`build_server`):
    ``MCP_ALLOW_EXECUTE`` must be unset and ``MCP_AUTH_TOKEN`` must be present.

    Payment is **off by default** (the service runs free), so the endpoint is
    byte-identical to the unmetered HTTP transport unless a ``payment_verifier`` is
    supplied. ``require_payment`` (default: ``$MCP_REQUIRE_PAYMENT``) fails closed:
    if payment is required but no verifier is wired, the app refuses to build,
    rather than silently serving a paid listing for free.
    """
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    if require_payment is None:
        require_payment = _payment_required_default()
    if require_payment and payment_verifier is None:
        # Fail-closed: build the signed-receipt verifier from the environment. If the
        # payment config (recipient + broker key) is incomplete this raises rather
        # than serve a paid listing for free.
        from runeclaw_okx.payments import SignedReceiptVerifier

        payment_verifier = SignedReceiptVerifier.from_env()

    server, _rc = build_server(rc_server)  # runs guards; constructs RuneClawMCPServer
    token = _resolve_auth_token()

    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=False,
        stateless=False,
        security_settings=_security_settings(),
    )

    async def _handle_mcp(scope: dict, receive: Callable, send: Callable) -> None:
        await manager.handle_request(scope, receive, send)

    async def _healthz(_request: Any) -> Any:
        # Unauthenticated liveness probe for reverse proxies / load balancers.
        return JSONResponse({"status": "ok", "service": "runeclaw-okx-mcp"})

    limiter = RateLimiter(limit=requests_per_minute, window_seconds=_RATE_WINDOW_SECONDS)
    # Order (outermost → innermost): auth → payment → MCP. Authenticate before
    # charging; only insert the payment gate when a verifier is configured.
    inner: ASGIApp = _handle_mcp
    if payment_verifier is not None:
        inner = PaymentASGIMiddleware(inner, payment_verifier)
    guarded_mcp = BearerAuthASGIMiddleware(inner, token, limiter)

    @contextlib.asynccontextmanager
    async def _lifespan(_app: Any):
        async with manager.run():
            yield

    return Starlette(
        routes=[
            Route("/healthz", _healthz, methods=["GET"]),
            Mount(mount_path, app=guarded_mcp),
        ],
        lifespan=_lifespan,
    )


def serve_http(
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    *,
    requests_per_minute: int = _DEFAULT_RPM,
) -> None:
    """Run the streamable-HTTP MCP server with uvicorn (localhost by default)."""
    import uvicorn

    app = build_http_app(requests_per_minute=requests_per_minute)
    uvicorn.run(app, host=host, port=port, log_level="info")
