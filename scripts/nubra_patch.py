"""
Nubra SDK Workshop Drop-in Adapter
Allows students to run official Nubra SDK code unmodified without individual accounts,
passwords, SMS OTPs, or MPIN prompts.

Usage in student scripts:
    import nubra_patch  # (Place at the top of your script)

    from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
    from nubra_python_sdk.refdata.instruments import InstrumentData
    from nubra_python_sdk.marketdata.market_data import MarketData
    from nubra_python_sdk.trading.trading_data import NubraTrader

    # Official Nubra initialization runs transparently:
    nubra = InitNubraSdk(NubraEnv.UAT)
"""

import os
import sys

# Default to the live Tailscale Funnel gateway or local relay
DEFAULT_GATEWAY = "https://nubra-relay.tail2b15c4.ts.net"
GATEWAY_URL = os.getenv("NUBRA_GATEWAY_URL", DEFAULT_GATEWAY).rstrip("/")

try:
    from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv

    def _workshop_init(self, env=NubraEnv.UAT, *args, **kwargs):
        # 1. Point SDK to workshop relay gateway
        self.API_BASE_URL = GATEWAY_URL
        ws_base = GATEWAY_URL.replace("https://", "wss://").replace("http://", "ws://")
        self.WEBSOCKET_URL = f"{ws_base}/ws"
        self.WEBSOCKET_URL_BATCH = f"{ws_base}/apibatch/ws"
        self.WEBSOCKET_URL_OMS = f"{ws_base}/oms-socket-latest/ws"

        # 2. Virtual session without interactive terminal prompts
        self.token_data = {
            "auth_token": "STU_WORKSHOP",
            "session_token": "STU_WORKSHOP",
            "x-device-id": "workshop-pc"
        }
        self.totp_login = False
        self.env_path_login = False
        self.client_code = "STUDENT"
        self.exchange_client_code = "STUDENT"
        self.db_path = "auth_data.db"

        # 3. Transparent student headers
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer STU_WORKSHOP",
            "x-device-id": "workshop-pc",
            "x-app-version": "0.5.4",
            "x-device-os": "sdk"
        }
        type(self).HEADERS = headers
        type(self).BEARER_TOKEN = "STU_WORKSHOP"
        self.HEADERS = headers
        self.BEARER_TOKEN = "STU_WORKSHOP"

        # 4. Auto-populate instrument data via gateway
        if not type(self).FLAG.get("value"):
            self._get_instruments()
            type(self).FLAG["value"] = True

    # Monkeypatch InitNubraSdk
    InitNubraSdk.__init__ = _workshop_init

except ImportError:
    pass
