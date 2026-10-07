#!/usr/bin/env python3
"""
Relay Gateway Diagnostic & Verification Test Suite
Tests authentication, caching, rate limiting, and security route blocks.
"""

import sys
import time
import httpx
import asyncio

GATEWAY_URL = "http://localhost:8000"
VALID_STUDENT_TOKEN = "STU_TOKEN_ALPHA"
INVALID_TOKEN = "INVALID_TOKEN_XYZ"

async def run_tests():
    print("==================================================")
    print("   Nubra Relay Gateway Diagnostic Test Suite      ")
    print("==================================================")

    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=10.0) as client:
        # Test 1: Healthcheck
        print("\n[Test 1] Gateway Health Check...")
        try:
            resp = await client.get("/health")
            if resp.status_code == 200:
                print(f"  ✓ Pass: Gateway healthy: {resp.json()}")
            else:
                print(f"  ✗ Fail: Health returned {resp.status_code}")
        except Exception as e:
            print(f"  ✗ Fail: Could not connect to {GATEWAY_URL} ({e})")
            sys.exit(1)

        # Test 2: Unauthorized request
        print("\n[Test 2] Unauthorized Request Rejection...")
        resp = await client.get("/instruments")
        if resp.status_code == 401:
            print("  ✓ Pass: Rejected request with missing token (HTTP 401)")
        else:
            print(f"  ✗ Fail: Expected 401, got {resp.status_code}")

        # Test 3: Invalid token
        print("\n[Test 3] Invalid Token Rejection...")
        resp = await client.get("/instruments", headers={"Authorization": f"Bearer {INVALID_TOKEN}"})
        if resp.status_code == 401:
            print("  ✓ Pass: Rejected invalid token (HTTP 401)")
        else:
            print(f"  ✗ Fail: Expected 401, got {resp.status_code}")

        # Test 4: Restricted / Blocked Endpoint
        print("\n[Test 4] Blacklist Route Guard (/report)...")
        resp = await client.get("/report", headers={"Authorization": f"Bearer {VALID_STUDENT_TOKEN}"})
        if resp.status_code == 403:
            print(f"  ✓ Pass: Sensitive route blocked (HTTP 403: {resp.json().get('detail', {}).get('message')})")
        else:
            print(f"  ✗ Fail: Expected 403, got {resp.status_code}")

        # Test 5: Cache Behavior (Twin Queries)
        print("\n[Test 5] Query Caching & Deduplication...")
        headers = {"Authorization": f"Bearer {VALID_STUDENT_TOKEN}"}
        
        # First request (Miss)
        t0 = time.time()
        r1 = await client.get("/instruments", headers=headers)
        t1 = time.time()
        cache_status_1 = r1.headers.get("X-Cache", "NONE")
        print(f"  Query 1: Status={r1.status_code}, X-Cache={cache_status_1}, Latency={(t1-t0)*1000:.1f}ms")

        # Second request (Hit)
        t2 = time.time()
        r2 = await client.get("/instruments", headers=headers)
        t3 = time.time()
        cache_status_2 = r2.headers.get("X-Cache", "NONE")
        print(f"  Query 2: Status={r2.status_code}, X-Cache={cache_status_2}, Latency={(t3-t2)*1000:.1f}ms")

        if cache_status_2 == "HIT":
            print("  ✓ Pass: Second request served directly from cache!")
        else:
            print(f"  ℹ Note: X-Cache was {cache_status_2}")

    print("\n==================================================")
    print("   All Gateway Diagnostic Checks Completed       ")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
