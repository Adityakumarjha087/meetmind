"""Fixed-window rate limiter with a Redis backend (shared across replicas) and in-memory fallback."""

from __future__ import annotations

import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.logging import get_logger

log = get_logger(__name__)


class CounterStore(Protocol):
    def hit(self, key: str, window_s: int) -> int: ...


class MemoryCounterStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, window_s: int) -> int:
        now = time.monotonic()
        with self._lock:
            count, reset_at = self._data.get(key, (0, now + window_s))
            if now >= reset_at:
                count, reset_at = 0, now + window_s
            count += 1
            self._data[key] = (count, reset_at)
            if len(self._data) > 50_000:  # bound memory under key-spraying
                self._data = {k: v for k, v in self._data.items() if v[1] > now}
            return count


class RedisCounterStore:
    def __init__(self, url: str) -> None:
        import redis

        self._redis = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)

    def hit(self, key: str, window_s: int) -> int:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_s, nx=True)
        count, _ = pipe.execute()
        return int(count)


@dataclass(frozen=True)
class RateRule:
    prefix: str
    limit: int
    methods: frozenset[str] | None = None


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        store: CounterStore,
        rules: list[RateRule],
        default_limit: int,
        window_s: int = 60,
        exempt_prefixes: tuple[str, ...] = ("/health", "/socket.io", "/docs", "/openapi.json"),
        trust_proxy_headers: bool = False,
    ) -> None:
        super().__init__(app)
        self.store = store
        self.rules = rules
        self.default_limit = default_limit
        self.window_s = window_s
        self.exempt = exempt_prefixes
        self._fallback = MemoryCounterStore()
        self.trust_proxy_headers = trust_proxy_headers

    def _rule_for(self, path: str, method: str) -> tuple[str, int]:
        for rule in self.rules:
            if path.startswith(rule.prefix) and (rule.methods is None or method in rule.methods):
                return rule.prefix, rule.limit
        return "default", self.default_limit

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if request.method == "OPTIONS" or path.startswith(self.exempt):
            return await call_next(request)
        bucket, limit = self._rule_for(path, request.method)
        # X-Forwarded-For is client-controlled; only honour it behind a trusted proxy.
        forwarded = request.headers.get("x-forwarded-for", "") if self.trust_proxy_headers else ""
        client = forwarded.split(",")[0].strip() or (
            request.client.host if request.client else "unknown"
        )
        window = int(time.time() // self.window_s)
        key = f"meetmind:rl:{bucket}:{client}:{window}"
        try:
            count = self.store.hit(key, self.window_s)
        except Exception:  # Redis down: degrade to per-process limiting rather than fail open
            log.warning("rate_limit_store_unavailable")
            count = self._fallback.hit(key, self.window_s)
        remaining = max(0, limit - count)
        if count > limit:
            return JSONResponse(
                {"error": {"code": "rate_limited", "message": "Too many requests, slow down."}},
                status_code=429,
                headers={"Retry-After": str(self.window_s), "X-RateLimit-Limit": str(limit)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
