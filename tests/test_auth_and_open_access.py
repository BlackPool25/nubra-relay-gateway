import pytest
import httpx

pytestmark = pytest.mark.asyncio

class TestOpenAccessAndStudentAuth:
    """
    Validates open workshop access where students do not have pre-issued logins or tokens.
    All requests must succeed without 401 Unauthorized rejections.
    """

    async def test_request_without_any_auth_header(self, client: httpx.AsyncClient):
        """A bare request with no headers at all must be accepted and processed."""
        resp = await client.get("/optionchains/NIFTY/price")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert "X-Workshop-Student" in resp.headers
        assert "price" in resp.json()

    async def test_request_with_arbitrary_student_bearer_token(self, client: httpx.AsyncClient):
        """Students providing arbitrary custom tokens should be accepted."""
        custom_token = "student_team_alpha_custom_token_999"
        resp = await client.get(
            "/optionchains/NIFTY/price",
            headers={"Authorization": f"Bearer {custom_token}"}
        )
        assert resp.status_code == 200
        student_header = resp.headers.get("X-Workshop-Student")
        assert student_header is not None
        assert custom_token[:10] in student_header

    async def test_request_with_custom_x_student_key_header(self, client: httpx.AsyncClient):
        """Students sending X-Student-Key header instead of Authorization."""
        custom_key = "team_beta_custom_key"
        resp = await client.get(
            "/optionchains/NIFTY/price",
            headers={"X-Student-Key": custom_key}
        )
        assert resp.status_code == 200
        student_header = resp.headers.get("X-Workshop-Student")
        assert student_header is not None
        assert custom_key[:10] in student_header

    async def test_request_with_malformed_auth_header_does_not_crash(self, client: httpx.AsyncClient):
        """Students passing unconventional Authorization strings (e.g. Basic, Token, bare string)."""
        malformed_headers = [
            {"Authorization": "Basic dXNlcjpwYXNz"},
            {"Authorization": "Token some_token"},
            {"Authorization": "Bearer-Token-Without-Space"},
            {"Authorization": "Bearer dummy_token_abc_123"},
            {"Authorization": "gibberish_without_bearer"},
        ]
        for headers in malformed_headers:
            resp = await client.get("/optionchains/NIFTY/price", headers=headers)
            assert resp.status_code == 200, f"Failed on {headers}: status={resp.status_code}"

    async def test_master_credentials_are_never_leaked_downstream(self, client: httpx.AsyncClient):
        """Verify that the master JWT token or master device cookies are NEVER exposed to students."""
        resp = await client.get("/optionchains/NIFTY/price")
        assert resp.status_code == 200
        headers_str = str(resp.headers).lower()
        # Ensure no master session token signatures appear in client response headers
        assert "eyjhbgcioijsuzi" not in headers_str
        assert "deviceid=workshop-pc" not in headers_str
        # Check body as well
        assert "eyjhbgcioijsuzi" not in resp.text.lower()
