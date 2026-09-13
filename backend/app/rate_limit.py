"""
Simple in-memory per-IP rate limiting (Phase D slice 2: API security).

WHY A HAND-ROLLED LIMITER, NOT A LIBRARY
--------------------------------------------
This is one fixed-window counter per (client IP, endpoint tier), reset
once a minute. That's the whole algorithm. Pulling in a dependency
(slowapi, etc.) for something this small would be more surface area to
trust than the problem needs — same reasoning as db.py using stdlib
sqlite3 instead of an ORM. If this needs to grow into something with
per-user quotas, burst allowances, or distributed (multi-worker) state,
that's the trigger to introduce a real library and/or Redis, not before.

WHY THIS MATTERS MOST FOR THE LLM-CALLING ENDPOINTS
--------------------------------------------------------
/api/scan is cheap: local, deterministic, no external call. /api/explain,
/api/chat, and /api/fix all call out to an LLM provider — every
unauthenticated request against those has a real dollar cost. Without a
limit, anyone who finds the server URL can drain the configured
LLM_API_KEY's quota. See config.py's RATE_LIMIT_SCAN_PER_MINUTE /
RATE_LIMIT_LLM_PER_MINUTE for the two tiers this module enforces.

CAVEAT (same as job_cache.py's in-memory dict): this state is per-process.
Running multiple uvicorn workers means each worker enforces its own
independent limit rather than a shared one — fine for a single-worker dev
setup, not sufficient on its own for a multi-worker production deploy
(pair with a reverse-proxy-level limit, or move to Redis, at that point).
"""
import time
from collections import defaultdict
from typing import Dict, Tuple

from fastapi import HTTPException, Request

from .config import RATE_LIMIT_SCAN_PER_MINUTE, RATE_LIMIT_LLM_PER_MINUTE

WINDOW_SECONDS = 60

# (client_ip, tier) -> (window_start_epoch_seconds, count_in_this_window)
_counters: Dict[Tuple[str, str], Tuple[float, int]] = defaultdict(lambda: (0.0, 0))


def _client_ip(request: Request) -> str:
    # Respects a reverse proxy's X-Forwarded-For if present (first hop —
    # good enough for a single-proxy deployment; a multi-hop chain would
    # need a trusted-proxy allowlist to pick the right entry, out of scope
    # for this slice), otherwise falls back to the direct connection.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check(request: Request, tier: str, limit_per_minute: int) -> None:
    key = (_client_ip(request), tier)
    now = time.time()
    window_start, count = _counters[key]

    if now - window_start >= WINDOW_SECONDS:
        # New window
        _counters[key] = (now, 1)
        return

    if count >= limit_per_minute:
        retry_after = int(WINDOW_SECONDS - (now - window_start))
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded ({limit_per_minute} requests/minute for "
                f"this endpoint tier). Try again in {retry_after}s."
            ),
            headers={"Retry-After": str(max(retry_after, 1))},
        )

    _counters[key] = (window_start, count + 1)


def rate_limit_scan(request: Request) -> None:
    """FastAPI dependency for /api/scan — the looser tier."""
    _check(request, "scan", RATE_LIMIT_SCAN_PER_MINUTE)


def rate_limit_llm(request: Request) -> None:
    """FastAPI dependency for any endpoint that calls an LLM
    (explain/chat/fix and friends) — the tighter tier."""
    _check(request, "llm", RATE_LIMIT_LLM_PER_MINUTE)
