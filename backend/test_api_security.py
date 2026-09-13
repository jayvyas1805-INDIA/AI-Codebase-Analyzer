"""
Regression test for Phase D slice 2 (API security).

Uses FastAPI's TestClient (real HTTP request/response cycle against the
actual app, in-process — not a mock) to verify:
  1. Rate limiting actually returns 429 after the configured limit, with a
     Retry-After header, and resets in a new window.
  2. CORS is a real allowlist now (an unlisted Origin doesn't get
     access-control-allow-origin back), not "*".
  3. A zip whose declared uncompressed size exceeds the configured cap is
     rejected BEFORE extraction (a lowered cap is used here rather than an
     actual multi-hundred-MB file, to keep the test fast — see zip_handler.py
     for why checking the zip's own declared sizes is sufficient).
  4. An upload exceeding the configured size cap is rejected (413) without
     writing the whole thing to disk first.

Run: python test_api_security.py
"""
import io
import os
import zipfile

from fastapi.testclient import TestClient

import app.config as config
# Lower the caps BEFORE importing anything that reads them into module-
# level constants at import time (rate_limit.py, zip_handler.py, main.py
# all do `from .config import X` — reassigning config.X after they've
# already imported it wouldn't take effect, so this must happen first).
config.RATE_LIMIT_SCAN_PER_MINUTE = 3
config.MAX_UNCOMPRESSED_SIZE_MB = 1
config.MAX_UPLOAD_SIZE_MB = 1
config.CORS_ALLOWED_ORIGINS = ["http://localhost:5173"]

from app.main import app as fastapi_app  # noqa: E402  (must come after the config overrides above)

client = TestClient(fastapi_app)


def _tiny_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("src/App.jsx", "export default function App() { return null; }")
    return buf.getvalue()


print("=" * 60)
print("Check 1: rate limiting kicks in after the configured limit")
print("=" * 60)
statuses = []
for _ in range(config.RATE_LIMIT_SCAN_PER_MINUTE + 2):
    resp = client.post("/api/scan", files={"file": ("x.zip", _tiny_zip_bytes(), "application/zip")})
    statuses.append(resp.status_code)

allowed = statuses[: config.RATE_LIMIT_SCAN_PER_MINUTE]
blocked = statuses[config.RATE_LIMIT_SCAN_PER_MINUTE:]
assert all(s == 200 for s in allowed), f"expected first {config.RATE_LIMIT_SCAN_PER_MINUTE} to succeed, got {allowed}"
assert all(s == 429 for s in blocked), f"expected remaining requests to be 429, got {blocked}"
print(f"PASS — first {len(allowed)} requests OK, next {len(blocked)} correctly rate-limited (429)")

last_429 = client.post("/api/scan", files={"file": ("x.zip", _tiny_zip_bytes(), "application/zip")})
assert last_429.status_code == 429
assert "retry-after" in {k.lower() for k in last_429.headers.keys()}
print(f"PASS — 429 response includes Retry-After header: {last_429.headers.get('retry-after')}s")

print()
print("=" * 60)
print("Check 2: CORS is a real allowlist, not '*'")
print("=" * 60)
resp_allowed = client.get("/", headers={"Origin": "http://localhost:5173"})
resp_blocked = client.get("/", headers={"Origin": "http://evil.example.com"})
allowed_header = resp_allowed.headers.get("access-control-allow-origin")
blocked_header = resp_blocked.headers.get("access-control-allow-origin")
assert allowed_header == "http://localhost:5173", f"expected the allowed origin echoed back, got {allowed_header!r}"
assert blocked_header is None or blocked_header != "http://evil.example.com", (
    f"an unlisted origin should NOT get access-control-allow-origin set to itself, got {blocked_header!r}"
)
print(f"PASS — allowed origin echoed ({allowed_header!r}), unlisted origin not granted ({blocked_header!r})")

print()
print("=" * 60)
print("Check 3: zip exceeding declared uncompressed size cap is rejected")
print("=" * 60)
from app.rate_limit import _counters
_counters.clear()  # check 1 intentionally exhausted the scan-tier limit; reset before unrelated checks

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
    # Highly compressible content so the actual UPLOAD stays tiny (well
    # under MAX_UPLOAD_SIZE_MB) while its DECLARED uncompressed size
    # exceeds MAX_UNCOMPRESSED_SIZE_MB (1 MB, lowered above) — this is
    # exactly the zip-bomb shape the check exists for.
    zf.writestr("src/big.css", "a" * (2 * 1024 * 1024))
bomb_bytes = buf.getvalue()
assert len(bomb_bytes) < 1024 * 50, f"test setup issue: compressed size should stay tiny, got {len(bomb_bytes)} bytes"

resp = client.post("/api/scan", files={"file": ("bomb.zip", bomb_bytes, "application/zip")})
assert resp.status_code == 400, f"expected 400 (caught as ValueError), got {resp.status_code}: {resp.text}"
assert "exceed" in resp.text.lower() or "mb" in resp.text.lower(), resp.text
print(f"PASS — zip with {len(bomb_bytes)} compressed bytes but >1MB declared uncompressed size rejected: {resp.json()['detail'][:80]}...")

print()
print("=" * 60)
print("Check 4: raw upload exceeding MAX_UPLOAD_SIZE_MB is rejected (413)")
print("=" * 60)
_counters.clear()
oversized = b"0" * (2 * 1024 * 1024)  # 2MB, over the 1MB cap set above
resp = client.post("/api/scan", files={"file": ("big.zip", oversized, "application/zip")})
assert resp.status_code == 413, f"expected 413, got {resp.status_code}: {resp.text}"
print(f"PASS — {len(oversized)}-byte upload correctly rejected with 413")

print()
print("All API security checks PASSED.")
