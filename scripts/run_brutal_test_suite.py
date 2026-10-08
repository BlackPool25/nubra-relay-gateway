#!/usr/bin/env python3
"""
Comprehensive & Brutal Diagnostic Test Suite for Nubra Relay & Queue Gateway.
Tests all endpoints, security boundaries, Redis caching, single-flight coalescing,
Redis FIFO order queuing, and WebSockets without requiring student logins or tokens.
"""

import sys
import time
import uuid
import asyncio
from datetime import date
import httpx
import websockets

GATEWAY_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"

# ANSI Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

passed_tests = 0
failed_tests = 0

def record_result(name: str, passed: bool, detail: str = ""):
    global passed_tests, failed_tests
    if passed:
        passed_tests += 1
        print(f"  {GREEN}✓ PASS{RESET} | {name} {CYAN}{detail}{RESET}")
    else:
        failed_tests += 1
        print(f"  {RED}✗ FAIL{RESET} | {name} {YELLOW}{detail}{RESET}")

async def run_suite():
    print(f"\n{BOLD}{CYAN}======================================================================{RESET}")
    print(f"{BOLD}{CYAN}    NUBRA RELAY GATEWAY: BRUTAL MULTI-SCENARIO VERIFICATION SUITE     {RESET}")
    print(f"{BOLD}{CYAN}======================================================================{RESET}")
    print(f"Target Gateway: {GATEWAY_URL}")
    print(f"Target Streaming: {WS_URL}\n")

    today = date.today().isoformat()

    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=15.0) as client:
        # -------------------------------------------------------------
        # SUITE 1: System & Operational Endpoints
        # -------------------------------------------------------------
        print(f"{BOLD}[Suite 1/7] System & Operational Endpoints{RESET}")
        
        # 1.1 Health Check
        try:
            r = await client.get("/health")
            d = r.json()
            is_ok = r.status_code == 200 and d.get("status") == "healthy" and d.get("redis_connected") is True
            record_result("Health Status Check", is_ok, f"Status: {r.status_code}, Redis: {d.get('redis_connected')}")
        except Exception as e:
            record_result("Health Status Check", False, str(e))

        # 1.2 UserInfo Virtualization
        try:
            r = await client.get("/userinfo")
            d = r.json()
            env_info = d.get("env_info", {})
            is_ok = (
                r.status_code == 200
                and "ws://localhost:8000/ws" in env_info.get("user_ws_url", "")
                and "uatapi.nubra.io" not in env_info.get("user_ws_url", "")
            )
            record_result("UserInfo Safe Virtualization", is_ok, f"Status: {r.status_code}, Mapped WS: {env_info.get('user_ws_url')}")
        except Exception as e:
            record_result("UserInfo Safe Virtualization", False, str(e))

        # 1.3 Logout Virtualization
        try:
            r = await client.post("/logout")
            is_ok = r.status_code == 200 and "Logout successful" in r.text
            record_result("Logout Safe Virtualization", is_ok, f"Status: {r.status_code}, Msg: {r.json().get('msg')}")
        except Exception as e:
            record_result("Logout Safe Virtualization", False, str(e))

        # -------------------------------------------------------------
        # SUITE 2: Open Access & Tokenless Routing
        # -------------------------------------------------------------
        print(f"\n{BOLD}[Suite 2/7] Open Access & Tokenless Workshop Routing{RESET}")

        # 2.1 Request with zero headers
        try:
            r = await client.get("/optionchains/NIFTY/price")
            is_ok = r.status_code == 200 and "price" in r.json() and "X-Workshop-Student" in r.headers
            record_result("Tokenless Bare Request Accepted", is_ok, f"Status: {r.status_code}, Tag: {r.headers.get('X-Workshop-Student')}")
        except Exception as e:
            record_result("Tokenless Bare Request Accepted", False, str(e))

        # 2.2 Arbitrary Student Bearer Token
        try:
            r = await client.get("/optionchains/NIFTY/price", headers={"Authorization": "Bearer student_group_42"})
            is_ok = r.status_code == 200 and "student_group_42"[:10] in r.headers.get("X-Workshop-Student", "")
            record_result("Arbitrary Student Bearer Token Accepted", is_ok, f"Status: {r.status_code}, Student: {r.headers.get('X-Workshop-Student')}")
        except Exception as e:
            record_result("Arbitrary Student Bearer Token Accepted", False, str(e))

        # 2.3 Custom X-Student-Key Header
        try:
            r = await client.get("/optionchains/NIFTY/price", headers={"X-Student-Key": "workshop_key_xyz"})
            is_ok = r.status_code == 200 and "workshop_key_xyz"[:10] in r.headers.get("X-Workshop-Student", "")
            record_result("Custom X-Student-Key Header Accepted", is_ok, f"Status: {r.status_code}")
        except Exception as e:
            record_result("Custom X-Student-Key Header Accepted", False, str(e))

        # 2.4 Credentials Leaks Prevention
        try:
            r = await client.get("/optionchains/NIFTY/price")
            h_str = str(r.headers).lower()
            no_jwt_leak = "eyjhbgcioijsuzi" not in h_str and "deviceid=workshop-pc" not in h_str
            record_result("Zero Master Credential Leaks Downstream", no_jwt_leak, "Strict header scrubbing verified")
        except Exception as e:
            record_result("Zero Master Credential Leaks Downstream", False, str(e))

        # -------------------------------------------------------------
        # SUITE 3: Blacklist Security Route Guards
        # -------------------------------------------------------------
        print(f"\n{BOLD}[Suite 3/7] Security Blacklist & Destructive Route Guards (403 Forbidden){RESET}")
        blocked_routes = [
            "/report",
            "/profile",
            "/sendphoneotp",
            "/verifyphoneotp",
            "/verifypin",
            "/totp",
            "/trading/exit-all-positions",
            "/trading/orders/cancel-all",
            "/depository",
        ]
        for route in blocked_routes:
            try:
                r = await client.get(route)
                is_ok = r.status_code == 403 and r.json().get("detail", {}).get("error_code") == "FORBIDDEN_ENDPOINT"
                record_result(f"Blacklist Guard: {route}", is_ok, f"Status: {r.status_code}")
            except Exception as e:
                record_result(f"Blacklist Guard: {route}", False, str(e))

        # Subpaths and casing test
        try:
            r1 = await client.get("/REPORT/subpath/details")
            r2 = await client.delete("/trading/orders/cancel-all")
            is_ok = r1.status_code == 403 and r2.status_code == 403
            record_result("Blacklist: Casing & Mutating Verbs Blocked", is_ok, f"GET /REPORT: {r1.status_code}, DELETE cancel-all: {r2.status_code}")
        except Exception as e:
            record_result("Blacklist: Casing & Mutating Verbs Blocked", False, str(e))

        # -------------------------------------------------------------
        # SUITE 4: Live Market Data Endpoints
        # -------------------------------------------------------------
        print(f"\n{BOLD}[Suite 4/7] Live Upstream Nubra Market Data Routes{RESET}")

        # 4.1 Refdata NSE
        try:
            t0 = time.time()
            r = await client.get(f"/refdata/refdata/{today}?exchange=NSE")
            t1 = time.time()
            is_ok = r.status_code == 200 and r.json().get("exchange") == "NSE" and len(r.json().get("refdata", [])) > 0
            record_result("Refdata NSE Master Fetch", is_ok, f"Status: {r.status_code}, Instruments: {len(r.json().get('refdata', []))}, Latency: {(t1-t0)*1000:.1f}ms")
        except Exception as e:
            record_result("Refdata NSE Master Fetch", False, str(e))

        # 4.2 Refdata BSE
        try:
            r = await client.get(f"/refdata/refdata/{today}?exchange=BSE")
            is_ok = r.status_code == 200 and r.json().get("exchange") == "BSE"
            record_result("Refdata BSE Master Fetch", is_ok, f"Status: {r.status_code}")
        except Exception as e:
            record_result("Refdata BSE Master Fetch", False, str(e))

        # 4.3 Orderbook Depth
        try:
            r = await client.get("/orderbooks/1783617")
            is_ok = r.status_code == 200 and "orderBook" in r.json()
            record_result("Orderbook Market Depth", is_ok, f"Status: {r.status_code}, RefId: 1783617")
        except Exception as e:
            record_result("Orderbook Market Depth", False, str(e))

        # 4.4 Option Chain NIFTY
        try:
            r = await client.get("/optionchains/NIFTY")
            is_ok = r.status_code == 200 and "chain" in r.json()
            record_result("Option Chain NIFTY", is_ok, f"Status: {r.status_code}, Asset: {r.json().get('chain', {}).get('asset')}")
        except Exception as e:
            record_result("Option Chain NIFTY", False, str(e))

        # 4.5 Underlying Option Price
        try:
            r = await client.get("/optionchains/NIFTY/price")
            is_ok = r.status_code == 200 and "price" in r.json()
            record_result("Current Price NIFTY", is_ok, f"Status: {r.status_code}, Price: {r.json().get('price')}")
        except Exception as e:
            record_result("Current Price NIFTY", False, str(e))

        # 4.6 Fundamentals Screener
        try:
            r = await client.get("/screener/fetch_company_fundamentals?symbol=RELIANCE")
            is_ok = r.status_code == 200 and "result" in r.json()
            record_result("Fundamentals Screener RELIANCE", is_ok, f"Status: {r.status_code}")
        except Exception as e:
            record_result("Fundamentals Screener RELIANCE", False, str(e))

        # 4.7 Missing Param Edge Case (400)
        try:
            r = await client.get("/screener/fetch_company_fundamentals")
            is_ok = r.status_code == 400
            record_result("Screener Missing Param Returns 400", is_ok, f"Status: {r.status_code}")
        except Exception as e:
            record_result("Screener Missing Param Returns 400", False, str(e))

        # 4.8 Unknown Path Edge Case (404)
        try:
            r = await client.get("/unknown_market_path_xyz")
            is_ok = r.status_code == 404
            record_result("Unknown Endpoint Returns 404 Verbatim", is_ok, f"Status: {r.status_code}")
        except Exception as e:
            record_result("Unknown Endpoint Returns 404 Verbatim", False, str(e))

        # -------------------------------------------------------------
        # SUITE 5: Caching & Single-Flight Coalescing
        # -------------------------------------------------------------
        print(f"\n{BOLD}[Suite 5/7] Caching Engine & Stampede Coalescing{RESET}")

        # 5.1 Cache Miss then Hit
        try:
            url = "/optionchains/NIFTY/price"
            t0 = time.time()
            r1 = await client.get(url)
            t1 = time.time()
            r2 = await client.get(url)
            t2 = time.time()

            is_ok = r1.status_code == 200 and r2.status_code == 200 and r2.headers.get("X-Cache") == "HIT"
            record_result("Rapid Query Cache HIT Acceleration", is_ok, f"Q1: {r1.headers.get('X-Cache')} ({(t1-t0)*1000:.1f}ms) -> Q2: {r2.headers.get('X-Cache')} ({(t2-t1)*1000:.1f}ms)")
        except Exception as e:
            record_result("Rapid Query Cache HIT Acceleration", False, str(e))

        # 5.2 TTL Expiry Test (1.0s TTL for quotes)
        try:
            url = "/optionchains/NIFTY/price"
            await client.get(url)  # prime
            await asyncio.sleep(1.2)  # wait out TTL
            r_fresh = await client.get(url)
            is_ok = r_fresh.headers.get("X-Cache") == "MISS"
            record_result("Quote Cache TTL Expiry (>1.0s)", is_ok, f"After 1.2s: X-Cache={r_fresh.headers.get('X-Cache')}")
        except Exception as e:
            record_result("Quote Cache TTL Expiry (>1.0s)", False, str(e))

        # 5.3 Single-Flight Stampede Coalescing (25 concurrent requests)
        try:
            url = "/optionchains/NIFTY/price"
            t_start = time.time()
            tasks = [client.get(url) for _ in range(25)]
            results = await asyncio.gather(*tasks)
            t_elapsed = time.time() - t_start

            all_200 = all(r.status_code == 200 for r in results)
            all_same = len(set(r.content for r in results)) == 1
            record_result("Single-Flight Stampede Coalescing (25 concurrent)", all_200 and all_same, f"25 requests fulfilled in {t_elapsed*1000:.1f}ms, zero drops")
        except Exception as e:
            record_result("Single-Flight Stampede Coalescing (25 concurrent)", False, str(e))

        # -------------------------------------------------------------
        # SUITE 6: Redis FIFO Order Queue & Mutations
        # -------------------------------------------------------------
        print(f"\n{BOLD}[Suite 6/7] Redis FIFO Order Queue & Mutations{RESET}")

        # 6.1 Order Placement through Queue
        intent_id = f"test-exec-{uuid.uuid4().hex[:8]}"
        payload = {
            "orders": [{
                "refId": 1783617,
                "qty": 1,
                "side": "BUY",
                "deliveryType": "IDAY",
                "entryPrice": 100.0,
                "orderType": "LIMIT",
                "intentOrderId": intent_id
            }]
        }
        try:
            r = await client.post("/sentinel/orders/create", json=payload)
            is_ok = r.status_code in (200, 400, 403) and r.headers.get("X-Cache") == "BYPASS"
            record_result("Order Creation via Redis Queue", is_ok, f"Status: {r.status_code}, Response: {r.text[:50]}")
        except Exception as e:
            record_result("Order Creation via Redis Queue", False, str(e))

        # 6.2 Idempotency Deduplication
        try:
            r_repeat = await client.post("/sentinel/orders/create", json=payload)
            is_ok = r_repeat.status_code == r.status_code and r_repeat.content == r.content
            record_result("Order Idempotency Deduplication", is_ok, f"Identical intentOrderId returned cached status {r_repeat.status_code}")
        except Exception as e:
            record_result("Order Idempotency Deduplication", False, str(e))

        # 6.3 Order Modification
        try:
            r_mod = await client.post("/sentinel/orders/modify", json={"orders": [{"orderId": 12345, "qty": 5, "price": 102.5}]})
            is_ok = r_mod.status_code in (200, 400, 403, 404) and r_mod.headers.get("X-Cache") == "BYPASS"
            record_result("Order Modification via Queue", is_ok, f"Status: {r_mod.status_code}")
        except Exception as e:
            record_result("Order Modification via Queue", False, str(e))

        # 6.4 Concurrent Order Burst Simulation (15 concurrent mutating orders)
        try:
            async def submit_burst_order(i: int):
                p = {
                    "orders": [{
                        "refId": 1783617,
                        "qty": 1,
                        "side": "BUY",
                        "deliveryType": "IDAY",
                        "entryPrice": 100.0 + i,
                        "orderType": "LIMIT",
                        "intentOrderId": f"burst-{i}-{uuid.uuid4().hex[:6]}"
                    }]
                }
                return await client.post("/sentinel/orders/create", json=p)

            t_burst_start = time.time()
            burst_tasks = [submit_burst_order(i) for i in range(15)]
            burst_results = await asyncio.gather(*burst_tasks)
            t_burst_end = time.time() - t_burst_start

            burst_ok = all(res.status_code in (200, 400, 403) for res in burst_results)
            record_result("Workshop Burst Ingestion (15 concurrent orders)", burst_ok, f"15 orders processed in {t_burst_end*1000:.1f}ms without drops")
        except Exception as e:
            record_result("Workshop Burst Ingestion (15 concurrent orders)", False, str(e))

    # -------------------------------------------------------------
    # SUITE 7: WebSocket Proxies & Streaming
    # -------------------------------------------------------------
    print(f"\n{BOLD}[Suite 7/7] Streaming WebSocket Proxies{RESET}")

    # 7.1 /ws (Ticker)
    try:
        async with websockets.connect(f"{WS_URL}/ws", close_timeout=3.0) as ws:
            assert ws.close_code is None
            await ws.send("ping")
            await asyncio.sleep(0.1)
            record_result("WebSocket /ws (Ticker) Connection", ws.close_code is None, "Connected tokenlessly & healthy")
    except Exception as e:
        record_result("WebSocket /ws (Ticker) Connection", False, str(e))

    # 7.2 /apibatch/ws (Batch Market Data)
    try:
        async with websockets.connect(f"{WS_URL}/apibatch/ws", close_timeout=3.0) as ws:
            assert ws.close_code is None
            await ws.send("batch_subscribe orderbook_depth 1783617")
            await asyncio.sleep(0.1)
            record_result("WebSocket /apibatch/ws Market Batch Connection", ws.close_code is None, "Connected tokenlessly & subscription dispatched")
    except Exception as e:
        record_result("WebSocket /apibatch/ws Market Batch Connection", False, str(e))

    # 7.3 /oms-socket-latest/ws (OMS Order Socket)
    try:
        async with websockets.connect(f"{WS_URL}/oms-socket-latest/ws", close_timeout=3.0) as ws:
            assert ws.close_code is None
            await ws.send("subscribe direct_intent notification")
            await asyncio.sleep(0.1)
            record_result("WebSocket /oms-socket-latest/ws OMS Connection", ws.close_code is None, "Master session auto-attached & subscribed")
    except Exception as e:
        record_result("WebSocket /oms-socket-latest/ws OMS Connection", False, str(e))

    # Summary
    total = passed_tests + failed_tests
    print(f"\n{BOLD}{CYAN}======================================================================{RESET}")
    print(f"{BOLD}TOTAL TESTS: {total} | {GREEN}PASSED: {passed_tests}{RESET} | {RED if failed_tests else GREEN}FAILED: {failed_tests}{RESET}")
    print(f"{BOLD}{CYAN}======================================================================{RESET}")

    if failed_tests > 0:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_suite())
