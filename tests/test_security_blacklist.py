import pytest
import httpx

pytestmark = pytest.mark.asyncio

BLOCKED_PREFIXES = [
    "/report",
    "/profile",
    "/sendphoneotp",
    "/verifyphoneotp",
    "/verifypin",
    "/totp",
    "/login-insti",
    "/api-keys/login",
    "/reset_password",
    "/ipaddress",
    "/trading/exit-all-positions",
    "/trading/orders/cancel-all",
    "/depository",
]

class TestSecurityBlacklist:
    """
    Rigorously tests the route blacklist guards protecting the master account from
    destructive operations, credential resets, and confidential profile leaks.
    """

    @pytest.mark.parametrize("path", BLOCKED_PREFIXES)
    async def test_blocked_root_endpoints(self, client: httpx.AsyncClient, path: str):
        """Every root blocked endpoint must return 403 Forbidden with FORBIDDEN_ENDPOINT."""
        resp = await client.get(path)
        assert resp.status_code == 403, f"Expected 403 for {path}, got {resp.status_code}"
        data = resp.json()
        assert data.get("detail", {}).get("error_code") == "FORBIDDEN_ENDPOINT"

    @pytest.mark.parametrize("path", BLOCKED_PREFIXES)
    async def test_blocked_subpaths(self, client: httpx.AsyncClient, path: str):
        """Sub-paths of blocked prefixes must also be strictly blocked."""
        subpath = f"{path}/subpath/operation"
        resp = await client.get(subpath)
        assert resp.status_code == 403, f"Expected 403 for {subpath}, got {resp.status_code}"

    @pytest.mark.parametrize("path", ["/REPORT", "/Profile", "/SendPhoneOtp", "/DEPOSITORY/edis"])
    async def test_case_insensitive_blocking(self, client: httpx.AsyncClient, path: str):
        """Casing variations must not bypass the security filter."""
        resp = await client.get(path)
        assert resp.status_code == 403, f"Expected 403 for {path}, got {resp.status_code}"

    @pytest.mark.parametrize("method", ["get", "post", "put", "delete", "patch"])
    async def test_blocked_across_all_http_methods(self, client: httpx.AsyncClient, method: str):
        """Mutating or query HTTP methods must all be intercepted before reaching upstream."""
        func = getattr(client, method)
        resp = await func("/report")
        assert resp.status_code == 403, f"Expected 403 for {method.upper()} /report, got {resp.status_code}"

    async def test_blocked_with_query_parameters(self, client: httpx.AsyncClient):
        """Query parameters attached to sensitive endpoints must still trigger 403."""
        resp = await client.get("/report?start_date=2026-01-01&end_date=2026-10-08&type=pnl")
        assert resp.status_code == 403

    async def test_blocked_with_slashes_and_traversal(self, client: httpx.AsyncClient):
        """Trailing slashes and redundant slashes must be blocked."""
        paths = ["/report/", "/report//details", "/profile/", "/profile///settings", "/depository/edis/verify/"]
        for p in paths:
            resp = await client.get(p)
            assert resp.status_code == 403, f"Expected 403 for {p}, got {resp.status_code}"

        # Test double slash at root using absolute URL
        abs_resp = await client.get("http://localhost:8000//report")
        assert abs_resp.status_code == 403
