import time
import json
import hashlib
import asyncio
from typing import Optional, Tuple, Dict, Any, List
import redis.asyncio as aioredis
from app.config import RELAYED_RESPONSE_HEADERS, settings

class SingleFlightCoalescer:
    """
    Ensures that for any given cache key, only one upstream request is in flight.
    Concurrent twin requests wait on the same event and receive the resulting payload.
    """
    def __init__(self):
        self._events: Dict[str, asyncio.Event] = {}
        self._results: Dict[str, Tuple[int, bytes, Dict[str, str]]] = {}
        self._lock = asyncio.Lock()

    async def execute_or_wait(self, key: str, fetch_func):
        async with self._lock:
            if key in self._events:
                # An in-flight request already exists for this key. Wait for it!
                event = self._events[key]
                first_caller = False
            else:
                # We are the first caller for this key
                event = asyncio.Event()
                self._events[key] = event
                first_caller = True

        if not first_caller:
            await event.wait()
            return self._results.get(key)

        try:
            # First caller executes the fetch function
            result = await fetch_func()
            self._results[key] = result
            return result
        finally:
            async with self._lock:
                event.set()
                # Clean up event and buffered result shortly after notifying waiting callers
                self._events.pop(key, None)
                asyncio.create_task(self._delayed_cleanup(key))

    async def _delayed_cleanup(self, key: str, delay: float = 0.5):
        await asyncio.sleep(delay)
        self._results.pop(key, None)


class CacheManager:
    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._in_memory_store: Dict[str, Tuple[float, bytes, int, Dict[str, str]]] = {}
        self.coalescer = SingleFlightCoalescer()

    async def initialize(self):
        if not settings.ENABLE_CACHE:
            return
        if settings.REDIS_URL:
            try:
                self.redis = aioredis.from_url(
                    settings.REDIS_URL,
                    decode_responses=False,
                    socket_connect_timeout=2.0
                )
                await self.redis.ping()
                print("[Cache] Connected to Redis successfully.")
            except Exception as e:
                print(f"[Cache] Redis connection failed ({e}). Falling back to in-memory cache.")
                self.redis = None

    async def close(self):
        if self.redis:
            await self.redis.close()

    @staticmethod
    def generate_cache_key(method: str, path: str, query_params: dict, body: bytes = b"") -> str:
        clean_path = path.lower().lstrip("/")
        param_str = "&".join(f"{k}={v}" for k, v in sorted(query_params.items()))
        body_hash = hashlib.sha256(body).hexdigest()[:12] if body else ""
        query_hash = hashlib.sha256(param_str.encode("utf-8")).hexdigest()[:12] if param_str else ""

        # Semantic Key Tagging for Fine-Grained Invalidation
        if "orders" in clean_path:
            return f"nubra_cache:orders:{clean_path}:{query_hash}:{body_hash}"
        elif "funds" in clean_path:
            return f"nubra_cache:funds:{clean_path}:{query_hash}:{body_hash}"
        elif "orderbooks" in clean_path or "quotes" in clean_path:
            # Extract refId if present in path, e.g. orderbooks/97713
            parts = clean_path.split("/")
            ref_id = parts[-1] if len(parts) > 1 and parts[-1].isdigit() else "all"
            return f"nubra_cache:ref:{ref_id}:{clean_path}:{query_hash}"
        elif clean_path.startswith("instruments"):
            return f"nubra_cache:instruments:{clean_path}:{query_hash}"
        else:
            raw_key = f"{method.upper()}:{clean_path}:{param_str}:{body_hash}"
            return f"nubra_cache:gen:{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:16]}"

    def get_ttl_for_path(self, path: str) -> float:
        clean_path = path.lower().lstrip("/")
        if clean_path.startswith(("instruments", "refdata")):
            return settings.CACHE_TTL_INSTRUMENTS
        elif clean_path.startswith("orderbooks"):
            return settings.CACHE_TTL_ORDERBOOK
        elif clean_path.startswith(("quotes", "optionchains")):
            return settings.CACHE_TTL_QUOTES
        elif clean_path.startswith(("historical-data", "charts/")):
            return settings.CACHE_TTL_HISTORICAL
        elif "sentinel/orders" in clean_path:
            return 0.5
        elif "funds" in clean_path or "margin" in clean_path:
            return 15.0
        return settings.CACHE_TTL_DEFAULT

    @staticmethod
    def is_no_cache_path(path: str) -> bool:
        clean = "/" + path.lower().lstrip("/")
        return clean.startswith((
            "/sentinel/orders",
            "/sentinel/portfolio",
            "/sentinel/strategy-portfolio",
        ))

    async def get(self, key: str) -> Optional[Tuple[int, bytes, Dict[str, str]]]:
        if not settings.ENABLE_CACHE:
            return None

        # 1. Try Redis
        if self.redis:
            try:
                data = await self.redis.get(key)
                if data:
                    unpacked = json.loads(data.decode("utf-8"))
                    content = bytes.fromhex(unpacked["content_hex"])
                    return unpacked["status_code"], content, unpacked["headers"]
            except Exception:
                pass

        # 2. Try In-Memory
        if key in self._in_memory_store:
            expiry, content, status_code, headers = self._in_memory_store[key]
            if time.time() < expiry:
                return status_code, content, headers
            else:
                del self._in_memory_store[key]

        return None

    async def set(self, key: str, status_code: int, content: bytes, headers: Dict[str, str], ttl: float):
        if not settings.ENABLE_CACHE or status_code != 200:
            return

        safe_headers = {
            k: v for k, v in headers.items()
            if k.lower() in RELAYED_RESPONSE_HEADERS
        }

        # 1. Store in Redis
        if self.redis:
            try:
                payload = json.dumps({
                    "status_code": status_code,
                    "content_hex": content.hex(),
                    "headers": safe_headers
                }).encode("utf-8")
                await self.redis.set(key, payload, px=int(ttl * 1000))
                return
            except Exception:
                pass

        # 2. Store in Memory
        expiry = time.time() + ttl
        self._in_memory_store[key] = (expiry, content, status_code, safe_headers)

    async def invalidate_trade_state(self, ref_id: Optional[Any] = None, ref_ids: Optional[list] = None):
        """
        Event-driven cache invalidation triggered whenever an order is placed, modified, or cancelled.
        Purges active orders, funds/margin estimates, and affected symbol depth.
        Trading/portfolio GETs are no-cache passthrough, but gen:* keys from
        strategy/portfolio reads are purged defensively.
        """
        ids = list(ref_ids or [])
        if ref_id is not None:
            ids.append(ref_id)
        patterns = ["nubra_cache:orders*", "nubra_cache:funds*", "nubra_cache:gen*"]
        for rid in ids:
            patterns.append(f"nubra_cache:ref:{rid}*")

        # 1. Invalidate Redis
        if self.redis:
            try:
                for pattern in patterns:
                    cursor = b"0"
                    while cursor:
                        cursor, keys = await self.redis.scan(cursor=cursor, match=pattern, count=100)
                        if keys:
                            await self.redis.delete(*keys)
                        if cursor == 0 or cursor == b"0":
                            break
            except Exception as e:
                print(f"[Cache] Redis invalidation error: {e}")

        # 2. Invalidate In-Memory Store
        keys_to_delete = []
        for key in list(self._in_memory_store.keys()):
            for pattern in patterns:
                prefix = pattern.rstrip("*")
                if key.startswith(prefix):
                    keys_to_delete.append(key)
                    break

        for k in keys_to_delete:
            self._in_memory_store.pop(k, None)

        print(f"[Cache] Invalidated trade state cache (refIds={ids}, purged {len(keys_to_delete)} in-mem keys).")


cache_manager = CacheManager()
