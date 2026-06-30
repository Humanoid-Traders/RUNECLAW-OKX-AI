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
from typing import Any, Awaitable, Callable

from runeclaw_okx.transport import _resolve_auth_token, build_server

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
) -> Any:
    """Build the Starlette ASGI app exposing the analysis-only MCP server over HTTP.

    Enforces the same fail-closed guards as stdio (via :func:`build_server`):
    ``MCP_ALLOW_EXECUTE`` must be unset and ``MCP_AUTH_TOKEN`` must be present.
    """
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

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
    guarded_mcp = BearerAuthASGIMiddleware(_handle_mcp, token, limiter)

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
