"""Unit tests for the workshop-friendly OMS-disabled error mapping.

Pure function tests: no live gateway required.
"""
import json

from app.proxy import map_oms_disabled_response


class TestMapOmsDisabledResponse:
    def test_maps_upstream_oms_403(self):
        out = map_oms_disabled_response(403, b'{"error":"OMS v2 is not enabled"}')
        assert out is not None
        code, body = out
        assert code == 403  # status preserved
        data = json.loads(body.decode("utf-8"))
        assert data["status"] == "error"
        assert data["error_code"] == "OMS_DISABLED_UPSTREAM"
        assert "upstream_body" in data
        assert "message" in data and len(data["message"]) > 0

    def test_ignores_other_403s(self):
        assert map_oms_disabled_response(403, b'{"error":"FORBIDDEN_ENDPOINT"}') is None

    def test_ignores_non_403(self):
        assert map_oms_disabled_response(200, b'{"error":"OMS v2 is not enabled"}') is None

    def test_ignores_empty_body(self):
        assert map_oms_disabled_response(403, b"") is None
