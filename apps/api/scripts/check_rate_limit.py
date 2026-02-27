#!/usr/bin/env python3
"""
Check that IP-based "first free" rate limiting works.

Prerequisites: API and Redis running (e.g. docker compose up, or API on port 8000).
Default limit is 3 per IP per day; 4th request from same IP should get 429.

We send X-Forwarded-For: 127.0.0.1 so the API sees the same client IP for all
requests (avoids Docker/host giving different IPs and breaking the test).

Usage (from project root):
  cd apps/api
  API_URL=http://localhost:8000 PYTHONPATH=.. python3 scripts/check_rate_limit.py
"""
import os
import sys
import uuid

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
# Same IP for all requests so rate limit counts correctly (API uses X-Forwarded-For when set)
TEST_IP = "127.0.0.1"


def main():
    print(f"Using API: {API_URL}")
    print(f"Sending 4 POST /api/jobs (upload), same IP via X-Forwarded-For: {TEST_IP}")
    print("Expected: first 3 → 200, 4th → 429\n")

    results = []
    for i in range(4):
        uid = str(uuid.uuid4())
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{API_URL}/api/jobs",
                data=b'{"input_type":"upload"}',
                headers={
                    "Content-Type": "application/json",
                    "X-Anonymous-Id": uid,
                    "X-Forwarded-For": TEST_IP,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                results.append((i + 1, resp.status, None))
                print(f"  Request {i+1}: {resp.status} (allowed)")
        except urllib.error.HTTPError as e:
            results.append((i + 1, e.code, e.read()))
            print(f"  Request {i+1}: {e.code} (rate limited)" if e.code == 429 else f"  Request {i+1}: {e.code}")
        except Exception as e:
            results.append((i + 1, None, str(e)))
            print(f"  Request {i+1}: ERROR {e}")

    ok = (
        len(results) == 4
        and results[0][1] == 200
        and results[1][1] == 200
        and results[2][1] == 200
        and results[3][1] == 429
    )
    if ok:
        print("\n✓ Rate limit check passed: 3 allowed, 4th got 429.")
        sys.exit(0)
    else:
        print("\n✗ Rate limit check failed. Expected: 200,200,200,429.")
        sys.exit(1)


if __name__ == "__main__":
    main()
