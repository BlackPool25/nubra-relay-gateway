import pytest
import httpx
from datetime import date

pytestmark = pytest.mark.asyncio

class TestMarketDataEndpoints:
    """
    Rigorously tests live upstream Nubra market data routing, response structures,
    and input parameter edge cases.
    """

    async def test_nse_refdata_fetch(self, client: httpx.AsyncClient, today_str: str):
        """Fetches full instrument master for NSE and verifies JSON schema."""
        resp = await client.get(f"/refdata/refdata/{today_str}?exchange=NSE")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("exchange") == "NSE"
        assert "refdata" in data
        assert isinstance(data["refdata"], list)
        assert len(data["refdata"]) > 0

        # Validate structure of first instrument
        item = data["refdata"][0]
        assert "ref_id" in item
        assert "stock_name" in item

    async def test_bse_refdata_fetch(self, client: httpx.AsyncClient, today_str: str):
        """Fetches instrument master for BSE."""
        resp = await client.get(f"/refdata/refdata/{today_str}?exchange=BSE")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("exchange") == "BSE"

    async def test_mcx_refdata_fetch(self, client: httpx.AsyncClient, today_str: str):
        """Fetches instrument master for MCX."""
        resp = await client.get(f"/refdata/refdata/{today_str}?exchange=MCX")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("exchange") == "MCX"

    async def test_option_chain_fetch(self, client: httpx.AsyncClient):
        """Fetches live option chain for NIFTY."""
        resp = await client.get("/optionchains/NIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert "chain" in data
        chain = data["chain"]
        assert chain.get("asset") == "NIFTY"
        assert "ce" in chain
        assert "pe" in chain

    async def test_option_price_fetch(self, client: httpx.AsyncClient):
        """Fetches current underlying index price."""
        resp = await client.get("/optionchains/NIFTY/price")
        assert resp.status_code == 200
        data = resp.json()
        assert "price" in data
        assert "prev_close" in data

    async def test_orderbook_depth_fetch(self, client: httpx.AsyncClient):
        """Fetches orderbook market depth for a known instrument refId."""
        ref_id = 1783617
        resp = await client.get(f"/orderbooks/{ref_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "orderBook" in data
        ob = data["orderBook"]
        assert "ref_id" in ob
        assert "bid" in ob
        assert "ask" in ob

    async def test_company_fundamentals_screener_valid(self, client: httpx.AsyncClient):
        """Fetches company ratios and shareholding pattern for RELIANCE."""
        resp = await client.get("/screener/fetch_company_fundamentals?symbol=RELIANCE")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data

    async def test_company_fundamentals_screener_missing_param_returns_400(self, client: httpx.AsyncClient):
        """Calling screener without required symbol param returns upstream 400 error."""
        resp = await client.get("/screener/fetch_company_fundamentals")
        assert resp.status_code == 400
        assert "error" in resp.json()

    async def test_nonexistent_endpoint_returns_404(self, client: httpx.AsyncClient):
        """Querying an unknown route returns upstream 404 transparently."""
        resp = await client.get("/nonexistent/market/data/endpoint/xyz")
        assert resp.status_code == 404
