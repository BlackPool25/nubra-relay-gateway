"""
Student SDK Adapter for Nubra Python SDK (nubra-sdk)
Allows participants to use the official NubraTrader SDK client directly with
the workshop relay gateway without having to perform OTP/MPIN logins.
"""

from typing import Optional
try:
    from nubra_python_sdk.start_sdk import InitNubraSdk
    from nubra_python_sdk.trading.trading_data import NubraTrader
except ImportError:
    raise ImportError(
        "nubra-sdk is not installed. Install it with: pip install nubra-sdk"
    )

def get_relay_client(
    relay_url: str,
    student_token: str,
    device_id: str = "student-workstation"
) -> InitNubraSdk:
    """
    Creates an initialized Nubra SDK client targeting the workshop relay gateway.
    Bypasses interactive OTP and MPIN terminal login prompts.
    """
    client = InitNubraSdk.__new__(InitNubraSdk)
    base = relay_url.rstrip("/")
    client.API_BASE_URL = base
    # Point SDK sockets at the relay so NubraDataSocket/OrderUpdate work
    # without touching Nubra directly. ws:// for local, wss:// for funnel.
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    client.WEBSOCKET_URL = f"{ws_base}/ws"
    client.WEBSOCKET_URL_BATCH = f"{ws_base}/apibatch/ws"
    client.WEBSOCKET_URL_OMS = f"{ws_base}/oms-socket-latest/ws"
    client.db_path = "auth_data.db"
    client.totp_login = False
    client.token_data = {
        "auth_token": student_token,
        "session_token": student_token,
        "x-device-id": device_id
    }
    client.env_path_login = False

    # Bind headers to the relay token
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {student_token}",
        "x-device-id": device_id,
    }
    InitNubraSdk.HEADERS = headers
    InitNubraSdk.BEARER_TOKEN = student_token
    client.HEADERS = headers
    client.BEARER_TOKEN = student_token
    return client

def get_nubra_trader(
    relay_url: str,
    student_token: str,
    device_id: str = "student-workstation"
) -> NubraTrader:
    """
    Returns an authenticated NubraTrader instance pointing directly to the relay gateway.
    Students can use all standard methods like trader.create_order(), trader.orders(), etc.

    Example:
    >>> trader = get_nubra_trader("https://nubra-relay.<tailnet>.ts.net", "STU_TOKEN_01")
    >>> trader.create_order({
    ...     "refId": 71878,
    ...     "qty": 1,
    ...     "side": "BUY",
    ...     "deliveryType": "IDAY",
    ...     "priceType": "LIMIT",
    ...     "validityType": "DAY",
    ...     "isMultiLeg": False,
    ...     "executionMode": "ENTRY",
    ...     "entryPrice": 100000,  # integer paise
    ...     "stratTags": ["workshop-trade-01"],
    ... })
    """
    client = get_relay_client(relay_url, student_token, device_id)
    return NubraTrader(client)
