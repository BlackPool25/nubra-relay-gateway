"""Regression test: the relay must never forward upstream content-encoding.

httpx decodes upstream bodies, so re-advertising gzip makes clients gunzip
plain JSON (zlib.error: incorrect header check). Pure unit test.
"""
from app.config import RELAYED_RESPONSE_HEADERS


class TestRelayedHeaders:
    def test_no_content_encoding(self):
        lowered = [h.lower() for h in RELAYED_RESPONSE_HEADERS]
        assert "content-encoding" not in lowered
        assert "content-length" not in lowered

    def test_keeps_essentials(self):
        lowered = [h.lower() for h in RELAYED_RESPONSE_HEADERS]
        assert "content-type" in lowered
