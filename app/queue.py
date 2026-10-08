import time
import asyncio
from typing import Optional, Dict
import redis.asyncio as aioredis
from app.config import settings

class LocalTokenBucket:
    def __init__(self, capacity: float, rate_per_sec: float):
        self.capacity = float(capacity)
        self.rate = float(rate_per_sec)
        self.tokens = float(capacity)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now

                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                else:
                    wait_time = (1.0 - self.tokens) / self.rate
                    await asyncio.sleep(max(0.005, wait_time))


class DualRateLimiter:
    """
    Two-Tier Leaky/Token Bucket Governor matching official Nubra limits:
    1. Trading & General REST: Max 85 ops/sec (Nubra UAT ceiling: 100 ops/sec per IP)
    2. Historical Data: Max 50 req/min (Nubra REST ceiling: 60 req/min per IP)
    """
    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None

        # In-memory token buckets
        self.general_bucket = LocalTokenBucket(
            capacity=settings.MAX_UPSTREAM_RPS,
            rate_per_sec=settings.MAX_UPSTREAM_RPS
        )
        self.historical_bucket = LocalTokenBucket(
            capacity=settings.MAX_HISTORICAL_RPM,
            rate_per_sec=settings.MAX_HISTORICAL_RPM / 60.0
        )

    def set_redis(self, redis_client: Optional[aioredis.Redis]):
        self.redis = redis_client

    async def acquire(self, category: str = "general"):
        """
        Acquires an execution slot based on endpoint category: 'general' or 'historical'.
        """
        if category == "historical":
            capacity = settings.MAX_HISTORICAL_RPM
            rate = settings.MAX_HISTORICAL_RPM / 60.0
            bucket_key = "rate_limit:upstream:historical"
            local_bucket = self.historical_bucket
        else:
            capacity = settings.MAX_UPSTREAM_RPS
            rate = float(settings.MAX_UPSTREAM_RPS)
            bucket_key = "rate_limit:upstream:general"
            local_bucket = self.general_bucket

        if self.redis:
            try:
                allowed = await self._acquire_redis(bucket_key, capacity, rate)
                if allowed:
                    return
            except Exception:
                pass  # Fall back to local bucket

        await local_bucket.acquire()

    async def penalize(self, category: str = "general", delay: float = 1.0):
        """Back off after an upstream 429 so the next acquire waits out Retry-After."""
        bucket = self.historical_bucket if category == "historical" else self.general_bucket
        async with bucket._lock:
            bucket.tokens = min(bucket.tokens, 0.0)
            bucket.last_update = time.monotonic() + max(0.0, delay)
        if self.redis:
            try:
                key = "rate_limit:upstream:historical" if category == "historical" else "rate_limit:upstream:general"
                await self.redis.hset(key, mapping={"tokens": 0, "last": int(time.time() * 1000) + int(delay * 1000)})
            except Exception:
                pass

    async def _acquire_redis(self, key: str, capacity: float, rate: float) -> bool:
        lua_script = """
        local key = KEYS[1]
        local capacity = tonumber(ARGV[1])
        local rate = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])

        local data = redis.call('HMGET', key, 'tokens', 'last')
        local tokens = tonumber(data[1])
        local last = tonumber(data[2])

        if not tokens then
            tokens = capacity
            last = now
        else
            local elapsed = (now - last) / 1000.0
            tokens = math.min(capacity, tokens + elapsed * rate)
            last = now
        end

        if tokens >= 1.0 then
            tokens = tokens - 1.0
            redis.call('HMSET', key, 'tokens', tokens, 'last', last)
            redis.call('EXPIRE', key, 120)
            return 1
        else
            redis.call('HMSET', key, 'tokens', tokens, 'last', last)
            redis.call('EXPIRE', key, 120)
            return 0
        end
        """
        now_ms = int(time.time() * 1000)
        # Block until a token is available instead of leaking through on throttle.
        while True:
            res = await self.redis.eval(lua_script, 1, key, capacity, rate, now_ms)
            if res == 1:
                return True
            wait_interval = max(0.01, 1.0 / rate if rate > 0 else 0.1)
            await asyncio.sleep(min(1.0, wait_interval))
            now_ms = int(time.time() * 1000)

rate_limiter = DualRateLimiter()
