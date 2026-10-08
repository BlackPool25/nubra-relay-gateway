"""
Nubra SDK Workshop Drop-in Adapter
Allows students to run official Nubra SDK code unmodified without individual accounts,
passwords, SMS OTPs, or MPIN prompts.

Features:
- Transparently routes SDK requests to the workshop gateway.
- Pre-authenticates so students do not need phone numbers, OTPs, or MPINs.

Usage (required)::

    import nubra_workshop
    nubra_workshop.apply_patch()

    from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
    nubra = InitNubraSdk(NubraEnv.UAT)

Use ``nubra_workshop.status()`` to verify the patch is active.
"""

import importlib.abc
import os
import sys

__all__ = [
    "DEFAULT_GATEWAY",
    "GATEWAY_URL",
    "apply_patch",
    "is_active",
    "status",
]

DEFAULT_GATEWAY = "https://nubra-relay.tail2b15c4.ts.net"
GATEWAY_URL = os.getenv("NUBRA_GATEWAY_URL", DEFAULT_GATEWAY).rstrip("/")

_PATCH_APPLIED = False
_TARGET_URL = GATEWAY_URL


def _sdk_version():
    try:
        from importlib.metadata import version
        return version("nubra-sdk")
    except Exception:
        return "0.5.4"


def _target_url(gateway_url=None):
    return (gateway_url or os.getenv("NUBRA_GATEWAY_URL", DEFAULT_GATEWAY)).rstrip("/")


def is_active():
    """True when InitNubraSdk is currently routed to the workshop gateway."""
    if not _PATCH_APPLIED:
        return False
    try:
        from nubra_python_sdk.start_sdk import InitNubraSdk
        return getattr(InitNubraSdk.__init__, "__nubra_workshop__", False)
    except ImportError:
        return False


def status():
    """Diagnose adapter state. Call this when requests do not hit the gateway."""
    try:
        from nubra_python_sdk.start_sdk import InitNubraSdk
        init_name = getattr(InitNubraSdk.__init__, "__qualname__", repr(InitNubraSdk.__init__))
    except ImportError:
        init_name = "<nubra-sdk not installed>"
    return {
        "patch_applied": _PATCH_APPLIED,
        "active": is_active(),
        "gateway_url": _TARGET_URL,
        "sdk_init": init_name,
        "sdk_version": _sdk_version(),
    }


def apply_patch(gateway_url=None):
    """Route the official Nubra SDK through the workshop gateway.

    Idempotent: safe to call on every script start. Returns True when the
    patch is (or already was) active, False when nubra-sdk is not installed.
    """
    global _PATCH_APPLIED, _TARGET_URL
    target_url = _target_url(gateway_url)
    _TARGET_URL = target_url

    try:
        from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
    except ImportError:
        return False

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
            "x-app-version": _sdk_version(),
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

    _workshop_init.__nubra_workshop__ = True

    # Monkeypatch InitNubraSdk
    InitNubraSdk.__init__ = _workshop_init

    if not _PATCH_APPLIED and not os.getenv("NUBRA_QUIET"):
        print(f"[NubraWorkshop] Transparent gateway active -> {target_url}", file=sys.stderr)

    _PATCH_APPLIED = True
    return True


class _PatchLoader(importlib.abc.Loader):
    """Runs apply_patch() right after the SDK module finishes importing."""

    def __init__(self, origin):
        self._origin = origin

    def create_module(self, spec):
        create = getattr(self._origin, "create_module", None)
        return create(spec) if callable(create) else None

    def exec_module(self, module):
        self._origin.exec_module(module)
        apply_patch()


class _SdkImportHook(importlib.abc.MetaPathFinder):
    """Re-applies the patch when the SDK is imported after us.

    Why: a ``.pth``-triggered ``import nubra_workshop`` runs during site
    initialization, before ``nubra_python_sdk`` is importable, so the
    module-level ``apply_patch()`` below silently fails and the module stays
    cached. This hook retries the patch as soon as user code imports the SDK.
    """

    TARGET = "nubra_python_sdk.start_sdk"

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.TARGET or _PATCH_APPLIED:
            return None
        for finder in list(sys.meta_path):
            if finder is self:
                continue
            try:
                spec = finder.find_spec(fullname, path, target)
            except TypeError:
                try:
                    spec = finder.find_spec(fullname, path)
                except Exception:
                    continue
            except Exception:
                continue
            if spec is not None and spec.loader is not None:
                spec.loader = _PatchLoader(spec.loader)
                return spec
        return None


if not any(isinstance(f, _SdkImportHook) for f in sys.meta_path):
    sys.meta_path.insert(0, _SdkImportHook())

# Best-effort auto-apply for the common case (SDK already installed).
# When this runs too early (e.g. via .pth), _SdkImportHook retries later.
apply_patch()
