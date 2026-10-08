import os
from typing import List, Set
from pydantic_settings import BaseSettings

# Response headers safe to relay to students. content-encoding is excluded on
# purpose: httpx decodes upstream bodies, so re-advertising gzip corrupts clients.
RELAYED_RESPONSE_HEADERS = ("content-type", "x-request-id", "retry-after")

class Settings(BaseSettings):
    # Upstream Nubra Configuration
    NUBRA_UAT_BASE: str = "https://uatapi.nubra.io"
    NUBRA_SESSION_TOKEN: str = ""
    NUBRA_DEVICE_ID: str = ""

    # Workshop Student Security
    ENABLE_STUDENT_VERIFICATION: bool = False
    STUDENTS_FILE_PATH: str = "students.json"
    ALLOWED_STUDENT_TOKENS: str = "STU_TOKEN_ALPHA,STU_TOKEN_BRAVO,STU_TOKEN_CHARLIE,STU_DEMO"
    STUDENT_TOKEN_PREFIX: str = "STU_"

    # Cache & Rate Limiting (Aligned with official Nubra UAT limits: 100 ops/sec Trading, 60 req/min Historical)
    REDIS_URL: str = "redis://redis:6379/0"
    MAX_UPSTREAM_RPS: int = 85            # Ceiling is 100 ops/sec for UAT Trading & Orders
    MAX_HISTORICAL_RPM: int = 50          # Ceiling is 60 req/min for Historical Data REST API
    ENABLE_CACHE: bool = True

    # Cache TTLs in seconds
    CACHE_TTL_INSTRUMENTS: int = 3600
    CACHE_TTL_ORDERBOOK: float = 1.5
    CACHE_TTL_QUOTES: float = 1.0
    CACHE_TTL_HISTORICAL: float = 60.0
    CACHE_TTL_DEFAULT: float = 2.0

    # WebSocket Configuration
    NUBRA_UAT_WS_BASE: str = "wss://uatapi.nubra.io"

    # Redis Message Queue Configuration (Guarantees zero dropped orders during traffic spikes)
    ENABLE_REDIS_QUEUE: bool = True
    QUEUE_TIMEOUT_SECONDS: int = 25
    REDIS_QUEUE_URL: str = ""  # when empty, reuses REDIS_URL connection

    # Strict Blocklist (Blocked with 403 Forbidden to protect account safety)
    # Note: /userinfo and /logout are safe-intercepted and mocked in proxy.py instead of hard-blocked.
    BLOCKED_PREFIXES: List[str] = [
        "/report",
        "/profile",
        "/trading/exit-all-positions",
        "/trading/orders/cancel-all",
        # Auth/session endpoints: must never reach upstream with master token.
        # Students use pre-issued STU_* tokens; OTP/MPIN/TOTP flows would
        # invalidate or hang the shared master session.
        "/sendphoneotp",
        "/verifyphoneotp",
        "/verifypin",
        "/totp",
        "/login-insti",
        "/api-keys/login",
        "/reset_password",
        "/ipaddress",
        # eDIS browser/CDSL flow is per-account and unsafe to share.
        "/depository",
    ]

    @property
    def allowed_tokens_set(self) -> Set[str]:
        return {t.strip() for t in self.ALLOWED_STUDENT_TOKENS.split(",") if t.strip()}

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
