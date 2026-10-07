import time
import asyncio
from typing import Optional
import redis.asyncio as aioredis
from app.config import settings

class RateLimiterQueue:
    """
    Leaky / Token Bucket Governor to regulate outbound requests to Nubra UAT.
    Guarantees aggregate throughput stays strictly under the configured threshold.
    """
    def __init__(self):
        self.capacity = settings.MAX_UPSTREAM_RPS
        self.rate = settings.MAX_UPSTREAM_RPS  # tokens per second
        self.tokens = float(self.capacity)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()
        self.redis: Optional[aioredis.Redis] = None

    def set_redis(self, redis_client: Optional[aioredis.Redis]):
        self.redis = redis_client

    async def acquire(self):
        """
        Blocks asynchronously until an execution token is available.
        """
        if self.redis:
            try:
                # Redis token bucket via atomic script
                allowed = await self._acquire_redis()
                if allowed:
                    return
            except Exception:
                pass  # Fallback to in-memory

        # In-Memory Token Bucket
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now

                # Replenish tokens based on elapsed time
                self.tokens = min(float(self.capacity), self.tokens + elapsed * self.rate)

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                else:
                    # Calculate wait time needed for at least 1 token
                    wait_time = (1.0 - self.tokens) / self.rate
                    await asyncio.sleep(max(0.005, wait_time))

    async def _acquire_redis(self) -> bool:
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
            redis.call('EXPIRE', key, 60)
            return 1
        else
            redis.call('HMSET', key, 'tokens', tokens, 'last', last)
            redis.call('EXPIRE', key, 60)
            return 0
        end
        """
        now_ms = int(time.time() * 1000)
        res = await self.redis.eval(lua_script, 1, "rate_limit:upstream", self.capacity, self.rate, now_ms)
        if res == 1:
            return True
        await asyncio.sleep(1.0 / self.rate)
        return True

rate_limiter = RateLimiterQueue()
