"""
Nubra SDK Workshop Drop-in Adapter
Allows students to run official Nubra SDK code unmodified without individual accounts,
passwords, SMS OTPs, or MPIN prompts.

Features:
- Transparently routes SDK requests to the workshop gateway.
- Auto-activates on import or automatically via Python site-packages .pth hook.
- Pre-authenticates so students do not need phone numbers, OTPs, or MPINs.
"""

import os
import sys

DEFAULT_GATEWAY = "https://nubra-relay.tail2b15c4.ts.net"
GATEWAY_URL = os.getenv("NUBRA_GATEWAY_URL", DEFAULT_GATEWAY).rstrip("/")

_PATCH_APPLIED = False

def apply_patch(gateway_url=None):
    """Applies the transparent workshop monkeypatch to the official Nubra SDK."""
    global _PATCH_APPLIED
    target_url = (gateway_url or os.getenv("NUBRA_GATEWAY_URL", DEFAULT_GATEWAY)).rstrip("/")

    try:
        from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv

        def _workshop_init(self, env=NubraEnv.UAT, *args, **kwargs):
            # 1. Point SDK to workshop relay gateway
            self.API_BASE_URL = target_url
            ws_base = target_url.replace("https://", "wss://").replace("http://", "ws://")
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

        if not _PATCH_APPLIED and not os.getenv("NUBRA_QUIET"):
            print(f"[NubraWorkshop] Transparent gateway active -> {target_url}", file=sys.stderr)

        _PATCH_APPLIED = True
        return True

    except ImportError:
        return False

# Auto-apply immediately when module is imported
apply_patch()
