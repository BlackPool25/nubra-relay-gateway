import pytest
import httpx
from datetime import date

GATEWAY_BASE_URL = "http://localhost:8000"
WS_BASE_URL = "ws://localhost:8000"

@pytest.fixture
def base_url():
    return GATEWAY_BASE_URL

@pytest.fixture
def ws_url():
    return WS_BASE_URL

@pytest.fixture
def today_str():
    return date.today().isoformat()

@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=GATEWAY_BASE_URL, timeout=30.0) as ac:
        yield ac
