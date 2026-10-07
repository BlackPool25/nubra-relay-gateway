import os
from typing import List, Set
from pydantic_settings import BaseSettings

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

    # Cache & Rate Limiting
    REDIS_URL: str = "redis://redis:6379/0"
    MAX_UPSTREAM_RPS: int = 75
    ENABLE_CACHE: bool = True

    # Cache TTLs in seconds
    CACHE_TTL_INSTRUMENTS: int = 3600
    CACHE_TTL_ORDERBOOK: float = 1.5
    CACHE_TTL_QUOTES: float = 1.0
    CACHE_TTL_HISTORICAL: float = 60.0
    CACHE_TTL_DEFAULT: float = 2.0

    # Strict Blocklist (Blocked with 403 Forbidden)
    BLOCKED_PREFIXES: List[str] = [
        "/report",
        "/userinfo",
        "/profile",
        "/account",
        "/trading/exit-all-positions",
        "/trading/orders/cancel-all",
    ]

    @property
    def allowed_tokens_set(self) -> Set[str]:
        return {t.strip() for t in self.ALLOWED_STUDENT_TOKENS.split(",") if t.strip()}

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
