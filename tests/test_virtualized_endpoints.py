import pytest
import httpx

pytestmark = pytest.mark.asyncio

class TestVirtualizedEndpoints:
    """
    Validates virtualized / safe-intercepted endpoints that replace sensitive upstream
    session commands with controlled local gateway responses.
    """

    async def test_health_check(self, client: httpx.AsyncClient):
        """GET /health must return 200 with service health and Redis connectivity."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "healthy"
        assert data.get("service") == "nubra-relay-gateway"
        assert data.get("redis_connected") is True
        assert data.get("verification_enabled") is False

    async def test_userinfo_virtualization(self, client: httpx.AsyncClient):
        """
        GET /userinfo must return virtualized environment info with gateway WebSocket URLs,
        not leaking master user profile or upstream direct URLs.
        """
        resp = await client.get("/userinfo")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("message") == "workshop session"
        assert "env_info" in data

        env_info = data["env_info"]
        assert "user_ws_url" in env_info
        assert "market_ws_url" in env_info
        assert "order_service_ws_url" in env_info

        # Verify that WS URLs point to the relay gateway, NOT directly to upstream uatapi.nubra.io
        assert "uatapi.nubra.io" not in env_info["user_ws_url"]
        assert "/ws" in env_info["user_ws_url"]
        assert "/apibatch/ws" in env_info["market_ws_url"]
        assert "/oms-socket-latest/ws" in env_info["order_service_ws_url"]

    async def test_logout_virtualization(self, client: httpx.AsyncClient):
        """
        POST /logout must safely succeed without killing the shared master Nubra session.
        """
        resp = await client.post("/logout")
        assert resp.status_code == 200
        assert resp.json().get("msg") == "Logout successful"

        # Verify master session remains alive immediately following logout
        test_resp = await client.get("/optionchains/NIFTY/price")
        assert test_resp.status_code == 200, "Master session was invalidated by /logout call!"
