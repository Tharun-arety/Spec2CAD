"""Public API abuse, cost, and resource guardrails.

These controls are application limits, not substitutes for provider project
budgets. They deliberately fail closed and keep only hashed client identifiers.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
import time
from collections import OrderedDict, deque
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from spec2cad.extractors.base import openai_api_key
from spec2cad.store import Store


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class PublicLimits:
    requests_per_minute: int = 8
    ai_units_per_client_day: int = 12
    ai_units_global_day: int = 120
    max_concurrent_jobs: int = 1
    max_cached_runs: int = 8
    max_requirement_chars: int = 6_000
    max_conversation_messages: int = 12
    max_image_bytes: int = 5 * 1024 * 1024
    max_pdf_bytes: int = 10 * 1024 * 1024
    max_request_bytes: int = 12 * 1024 * 1024
    max_image_pixels: int = 16_000_000
    max_pdf_pages: int = 60

    @classmethod
    def from_env(cls) -> "PublicLimits":
        return cls(
            requests_per_minute=_integer("SPEC2CAD_REQUESTS_PER_MINUTE", 8, 1, 600),
            ai_units_per_client_day=_integer("SPEC2CAD_AI_UNITS_PER_CLIENT_DAY", 12, 1, 10000),
            ai_units_global_day=_integer("SPEC2CAD_AI_UNITS_GLOBAL_DAY", 120, 1, 1000000),
            max_concurrent_jobs=_integer("SPEC2CAD_MAX_CONCURRENT_JOBS", 1, 1, 16),
            max_cached_runs=_integer("SPEC2CAD_MAX_CACHED_RUNS", 8, 1, 1000),
            max_requirement_chars=_integer("SPEC2CAD_MAX_REQUIREMENT_CHARS", 6000, 100, 100000),
            max_conversation_messages=_integer("SPEC2CAD_MAX_CONVERSATION_MESSAGES", 12, 2, 100),
            max_image_bytes=_integer("SPEC2CAD_MAX_IMAGE_BYTES", 5 * 1024 * 1024, 1024, 50 * 1024 * 1024),
            max_pdf_bytes=_integer("SPEC2CAD_MAX_PDF_BYTES", 10 * 1024 * 1024, 1024, 100 * 1024 * 1024),
            max_request_bytes=_integer("SPEC2CAD_MAX_REQUEST_BYTES", 12 * 1024 * 1024, 1024, 120 * 1024 * 1024),
            max_image_pixels=_integer("SPEC2CAD_MAX_IMAGE_PIXELS", 16_000_000, 10000, 100_000_000),
            max_pdf_pages=_integer("SPEC2CAD_MAX_PDF_PAGES", 60, 1, 1000),
        )


_safety_identifier: ContextVar[str] = ContextVar(
    "spec2cad_safety_identifier", default="local-client"
)


def current_safety_identifier() -> str:
    return _safety_identifier.get()


def client_hash(request: Request) -> str:
    address = request.client.host if request.client else "unknown"
    if os.environ.get("SPEC2CAD_TRUST_PROXY", "0") == "1":
        # Use the hop appended by the trusted edge proxy, not a spoofable
        # left-most value supplied by the caller.
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if forwarded:
            address = forwarded
    salt = (
        os.environ.get("SPEC2CAD_USAGE_SALT")
        or openai_api_key()
        or "local-development-only"
    )
    return hashlib.sha256(f"{salt}:{address}".encode("utf-8")).hexdigest()


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock=time.monotonic):
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def admit(self, key: str) -> tuple[bool, int, int]:
        now = self.clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                retry = max(1, int(self.window_seconds - (now - events[0]) + 0.999))
                return False, 0, retry
            events.append(now)
            return True, self.limit - len(events), 0


class DailyAIBudget:
    def __init__(self, store: Store, client_limit: int, global_limit: int):
        self.store = store
        self.client_limit = client_limit
        self.global_limit = global_limit

    def reserve(self, key: str, units: int) -> tuple[int, int]:
        day = datetime.now(timezone.utc).date().isoformat()
        return self.store.reserve_api_units(
            day, key, units,
            client_limit=self.client_limit, global_limit=self.global_limit,
        )


class BoundedRunCache:
    def __init__(self, max_entries: int):
        self.max_entries = max_entries
        self._items: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str, default=None):
        with self._lock:
            value = self._items.get(key, default)
            if key in self._items:
                self._items.move_to_end(key)
            return value

    def __setitem__(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)


EXPENSIVE_POST_PATHS = {
    "/runs", "/runs/demo", "/assemblies/evaluate",
    "/inspection/evaluate", "/analyses/evaluate",
}


class PublicGuardrailMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limits: PublicLimits):
        super().__init__(app)
        self.limits = limits
        self.rate = SlidingWindowLimiter(limits.requests_per_minute)
        self.jobs = asyncio.Semaphore(limits.max_concurrent_jobs)

    async def dispatch(self, request: Request, call_next: Callable):
        length = request.headers.get("content-length")
        if length:
            try:
                too_large = int(length) > self.limits.max_request_bytes
            except ValueError:
                return JSONResponse({"detail": "invalid Content-Length"}, status_code=400)
            if too_large:
                return JSONResponse({"detail": "request body is too large"}, status_code=413)

        key = client_hash(request)
        request.state.client_hash = key
        token = _safety_identifier.set(key[:64])
        costly = request.method == "POST" and (
            request.url.path in EXPENSIVE_POST_PATHS
            or request.url.path.endswith("/messages")
            or request.url.path.endswith("/repair")
            or request.url.path.endswith("/revise")
        )
        acquired = False
        remaining = self.limits.requests_per_minute
        try:
            if costly:
                admitted, remaining, retry = self.rate.admit(key)
                if not admitted:
                    return JSONResponse(
                        {"detail": "public request rate limit reached"},
                        status_code=429, headers={"Retry-After": str(retry)},
                    )
                try:
                    await asyncio.wait_for(self.jobs.acquire(), timeout=0.05)
                    acquired = True
                except TimeoutError:
                    return JSONResponse(
                        {"detail": "the CAD worker is busy; retry shortly"},
                        status_code=503, headers={"Retry-After": "2"},
                    )
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            if costly:
                response.headers["X-RateLimit-Limit"] = str(self.limits.requests_per_minute)
                response.headers["X-RateLimit-Remaining"] = str(remaining)
            return response
        finally:
            if acquired:
                self.jobs.release()
            _safety_identifier.reset(token)
