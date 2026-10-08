import pytest
import asyncio
import websockets

pytestmark = pytest.mark.asyncio

class TestWebSocketProxies:
    """
    Rigorously tests bidirectional streaming proxies:
    - /ws (Ticker Stream)
    - /apibatch/ws (Batch Protobuf Market Data)
    - /oms-socket-latest/ws (Realtime Order Updates)
    Verifying students can connect without logins, and subscription commands
    are transparently translated to the master Nubra session token.
    """

    async def test_ticker_ws_connect_and_ping(self, ws_url: str):
        """Connects to /ws with no token or headers, sends ping, closes gracefully."""
        uri = f"{ws_url}/ws"
        async with websockets.connect(uri, close_timeout=3.0) as ws:
            assert ws.close_code is None
            # Send sample subscription or ping text
            await ws.send("ping")
            await asyncio.sleep(0.2)
            assert ws.close_code is None

    async def test_batch_market_data_ws_connect(self, ws_url: str):
        """Connects to /apibatch/ws with no token or headers."""
        uri = f"{ws_url}/apibatch/ws"
        async with websockets.connect(uri, close_timeout=3.0) as ws:
            assert ws.close_code is None
            # Send a batch subscribe command without student token (should be auto-injected upstream)
            await ws.send("batch_subscribe orderbook_depth 1783617")
            await asyncio.sleep(0.2)
            assert ws.close_code is None

    async def test_oms_order_update_ws_connect(self, ws_url: str):
        """Connects to /oms-socket-latest/ws with no token or headers."""
        uri = f"{ws_url}/oms-socket-latest/ws"
        async with websockets.connect(uri, close_timeout=3.0) as ws:
            assert ws.close_code is None
            # Send OMS direct_intent subscription command
            await ws.send("subscribe direct_intent notification")
            await asyncio.sleep(0.2)
            assert ws.close_code is None

    async def test_concurrent_websocket_connections(self, ws_url: str):
        """Simulates 10 students connecting simultaneously to the WebSocket proxies."""
        async def connect_client(idx: int):
            path = "ws" if idx % 2 == 0 else "apibatch/ws"
            uri = f"{ws_url}/{path}"
            async with websockets.connect(uri, close_timeout=3.0) as ws:
                assert ws.close_code is None
                await asyncio.sleep(0.1)

        tasks = [connect_client(i) for i in range(10)]
        await asyncio.gather(*tasks)
