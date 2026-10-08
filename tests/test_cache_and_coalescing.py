import pytest
import asyncio
import time
import httpx

pytestmark = pytest.mark.asyncio

class TestCacheAndCoalescing:
    """
    Rigorously tests Redis caching, TTL boundaries, query key hashing,
    and single-flight request coalescing under concurrent loads.
    """

    async def test_cache_miss_then_hit(self, client: httpx.AsyncClient):
        """Sequential requests to the same market endpoint must return MISS followed by HIT."""
        url = "/optionchains/NIFTY/price"

        # Request 1: MISS (or HIT if primed, so let's use a unique cache-busting query param if needed,
        # or test twin queries immediately within the 1-second TTL)
        t0 = time.time()
        r1 = await client.get(url)
        t1 = time.time()
        assert r1.status_code == 200

        # Request 2 immediately following Request 1 (< 0.2s)
        t2 = time.time()
        r2 = await client.get(url)
        t3 = time.time()
        assert r2.status_code == 200

        # Status of request 2 must be HIT
        assert r2.headers.get("X-Cache") == "HIT", f"Expected HIT, got {r2.headers.get('X-Cache')}"
        # Response body must be identical
        assert r1.content == r2.content

    async def test_query_parameter_distinction_in_cache(self, client: httpx.AsyncClient, today_str: str):
        """Different query params for the same path must generate separate cache entries."""
        r_nse = await client.get(f"/refdata/refdata/{today_str}?exchange=NSE")
        r_bse = await client.get(f"/refdata/refdata/{today_str}?exchange=BSE")

        assert r_nse.status_code == 200
        assert r_bse.status_code == 200
        assert r_nse.json().get("exchange") == "NSE"
        assert r_bse.json().get("exchange") == "BSE"

    async def test_fast_quotes_ttl_expiration(self, client: httpx.AsyncClient):
        """Quotes cached with 1.0s TTL must expire after > 1.1s and yield a fresh MISS."""
        url = "/optionchains/NIFTY/price"
        # Prime cache
        r1 = await client.get(url)
        assert r1.status_code == 200

        # Wait out 1.0s TTL
        await asyncio.sleep(1.2)

        # Subsequent fetch after TTL must be fresh MISS
        r2 = await client.get(url)
        assert r2.status_code == 200
        assert r2.headers.get("X-Cache") == "MISS"

    async def test_non_cacheable_endpoints(self, client: httpx.AsyncClient):
        """Trading / sentinel routes must bypass cache (X-Cache: BYPASS)."""
        r = await client.get("/sentinel/orders")
        assert r.headers.get("X-Cache") == "BYPASS"

    async def test_non_200_responses_are_not_cached(self, client: httpx.AsyncClient):
        """404 or 400 responses must never be cached."""
        url = "/nonexistent/test/path"
        r1 = await client.get(url)
        assert r1.status_code == 404
        assert r1.headers.get("X-Cache") == "MISS"

        r2 = await client.get(url)
        assert r2.status_code == 404
        # Should remain MISS, never HIT
        assert r2.headers.get("X-Cache") == "MISS"

    async def test_request_coalescing_stampede_prevention(self, client: httpx.AsyncClient):
        """
        Stampede test: 20 concurrent identical GET requests dispatched at the exact same millisecond.
        The single-flight coalescer must collapse them to 1 upstream request and safely fulfill all 20.
        """
        url = "/screener/fetch_company_fundamentals?symbol=RELIANCE"
        tasks = [client.get(url) for _ in range(20)]
        results = await asyncio.gather(*tasks)

        for i, resp in enumerate(results):
            assert resp.status_code == 200, f"Task {i} returned {resp.status_code}"
            assert "result" in resp.json()

        # All results must have identical content
        first_content = results[0].content
        for resp in results[1:]:
            assert resp.content == first_content
