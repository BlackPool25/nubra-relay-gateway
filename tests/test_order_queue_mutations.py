import pytest
import asyncio
import uuid
import httpx

pytestmark = pytest.mark.asyncio

class TestOrderQueueMutations:
    """
    Rigorously tests the Redis FIFO Order Queue worker, idempotency deduplication,
    and concurrent order burst buffering for POST /sentinel/orders/* mutations.
    """

    async def test_order_creation_routing_through_queue(self, client: httpx.AsyncClient):
        """Dispatches an order creation payload through the Redis order queue."""
        intent_id = f"test-intent-{uuid.uuid4().hex[:8]}"
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
        resp = await client.post("/sentinel/orders/create", json=payload)
        # Upstream responds (either 200, 400, or 403 depending on OMS v2 account flags,
        # but the gateway must relay the response cleanly without 500 or timeout)
        assert resp.status_code in (200, 400, 403)
        assert resp.headers.get("X-Cache") == "BYPASS"
        assert "X-Workshop-Student" in resp.headers

    async def test_order_idempotency_deduplication(self, client: httpx.AsyncClient):
        """Submitting an identical order with same intentOrderId returns cached idempotent response."""
        intent_id = f"test-idem-{uuid.uuid4().hex[:8]}"
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

        # First dispatch
        resp1 = await client.post("/sentinel/orders/create", json=payload)
        assert resp1.status_code in (200, 400, 403)

        # Second dispatch with identical intentOrderId
        resp2 = await client.post("/sentinel/orders/create", json=payload)
        assert resp2.status_code == resp1.status_code
        assert resp2.content == resp1.content

    async def test_order_modification_routing(self, client: httpx.AsyncClient):
        """Dispatches an order modification payload through the queue."""
        payload = {
            "orders": [{
                "orderId": 999999,
                "qty": 2,
                "price": 105.0
            }]
        }
        resp = await client.post("/sentinel/orders/modify", json=payload)
        assert resp.status_code in (200, 400, 403, 404)
        assert resp.headers.get("X-Cache") == "BYPASS"

    async def test_order_cancellation_routing(self, client: httpx.AsyncClient):
        """Dispatches an order cancellation payload through the queue."""
        payload = {
            "orders": [{
                "orderId": 999999
            }]
        }
        resp = await client.post("/sentinel/orders/cancel", json=payload)
        assert resp.status_code in (200, 400, 403, 404)
        assert resp.headers.get("X-Cache") == "BYPASS"

    async def test_concurrent_order_burst(self, client: httpx.AsyncClient):
        """
        Workshop Burst Simulation: 20 students concurrently place orders at the same instant.
        Redis FIFO queue must buffer and process all 20 orders without dropping any.
        """
        async def submit_order(idx: int):
            intent_id = f"burst-intent-{idx}-{uuid.uuid4().hex[:6]}"
            payload = {
                "orders": [{
                    "refId": 1783617,
                    "qty": 1,
                    "side": "BUY",
                    "deliveryType": "IDAY",
                    "entryPrice": 100.0 + idx,
                    "orderType": "LIMIT",
                    "intentOrderId": intent_id
                }]
            }
            return await client.post("/sentinel/orders/create", json=payload)

        tasks = [submit_order(i) for i in range(20)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 20
        for i, resp in enumerate(results):
            assert resp.status_code in (200, 400, 403), f"Order {i} failed with unexpected code: {resp.status_code}"
            assert resp.headers.get("X-Cache") == "BYPASS"
