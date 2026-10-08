import json
import uuid
import base64
import asyncio
import time
from typing import Optional, Tuple, Dict, Any, Callable
from app.config import settings
from app.queue import rate_limiter

QUEUE_KEY = "nubra:queue:orders"
PROCESSING_KEY = "nubra:queue:orders:processing"
RES_KEY_PREFIX = "nubra:res:"
IDEMPOTENCY_PREFIX = "nubra:idem:"


def _resolve_client(client_pool):
    if callable(client_pool):
        try:
            return client_pool()
        except Exception:
            return None
    return client_pool


class RedisOrderQueue:
    """
    Guaranteed Delivery FIFO Message Queue for Order Mutations (POST /sentinel/orders/*).
    Ensures burst traffic from workshops is buffered safely in Redis and dispatched
    sequentially at Nubra's exact allowed throughput (85 ops/sec) without dropping requests.

    Reliability: BRPOPLPUSH pending -> processing + per-task ACK + startup reaper
    requeues orphaned jobs. Idempotency keys dedupe client retries.
    """
    def __init__(self):
        self.redis = None
        self._owns_redis = False
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

    def set_redis(self, redis_client, owns: bool = False):
        self.redis = redis_client
        self._owns_redis = owns

    async def start_worker(self, client_pool):
        """Starts the background worker draining the Redis order queue."""
        if self._running:
            return
        self._running = True
        await self._requeue_orphans()
        self._worker_task = asyncio.create_task(self._process_queue_loop(client_pool))
        print("[OrderQueue] Background Redis order queue worker started.")

    async def stop_worker(self):
        """Stops the background queue worker gracefully."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        if self._owns_redis and self.redis is not None:
            try:
                await self.redis.close()
            except Exception:
                pass
            self.redis = None
            self._owns_redis = False
        print("[OrderQueue] Background Redis order queue worker stopped.")

    async def _requeue_orphans(self):
        if not self.redis:
            return
        try:
            while True:
                item = await self.redis.rpop(PROCESSING_KEY)
                if not item:
                    break
                await self.redis.rpush(QUEUE_KEY, item)
                print("[OrderQueue] Requeued orphaned job from processing list.")
        except Exception as e:
            print(f"[OrderQueue] Orphan requeue failed: {e}")

    async def _ack(self, raw_payload: bytes):
        try:
            await self.redis.lrem(PROCESSING_KEY, 1, raw_payload)
        except Exception:
            pass

    async def enqueue_and_wait(
        self,
        method: str,
        path: str,
        student_id: str,
        query_params: dict,
        body: bytes,
        headers: dict,
        timeout: float = 25.0
    ) -> Optional[Tuple[int, bytes, Dict[str, str]]]:
        """
        Enqueues order request to Redis and awaits response from background worker.
        Falls back to direct dispatch (returns None) when Redis is unavailable.
        """
        if not self.redis:
            return None

        task_id = str(uuid.uuid4())
        idem_key = self._idempotency_key(student_id, method, path, body)
        if idem_key:
            try:
                cached = await self.redis.get(f"{IDEMPOTENCY_PREFIX}{idem_key}")
                if cached:
                    data = json.loads(cached.decode("utf-8") if isinstance(cached, bytes) else cached)
                    return (data["status_code"],
                            base64.b64decode(data["content_b64"]),
                            data["headers"])
            except Exception:
                pass

        payload = {
            "task_id": task_id,
            "method": method,
            "path": path,
            "student_id": student_id,
            "query_params": query_params,
            "body_b64": base64.b64encode(body).decode("ascii") if body else "",
            "content_type": headers.get("content-type", "application/json"),
            "idem_key": idem_key,
            "enqueued_at": time.time(),
        }

        await self.redis.lpush(QUEUE_KEY, json.dumps(payload))

        res_key = f"{RES_KEY_PREFIX}{task_id}"
        try:
            res = await self.redis.blpop(res_key, timeout=int(timeout))
            if res:
                _, raw_data = res
                data = json.loads(raw_data.decode("utf-8") if isinstance(raw_data, bytes) else raw_data)
                status_code = data["status_code"]
                content = base64.b64decode(data["content_b64"])
                resp_headers = data["headers"]
                return status_code, content, resp_headers
        except Exception as e:
            print(f"[OrderQueue] Error awaiting response for task {task_id}: {e}")

        return None

    @staticmethod
    def _idempotency_key(student_id: str, method: str, path: str, body: bytes) -> str:
        try:
            if not body:
                return ""
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                intent = (parsed.get("intentOrderId") or parsed.get("intent_order_id")
                          or (parsed.get("orders") or [{}])[0].get("intentOrderId") if isinstance(parsed.get("orders"), list) else None)
                if intent:
                    return f"{student_id}:{method}:{path}:{intent}"
        except Exception:
            pass
        return ""

    async def _process_queue_loop(self, client_pool):
        """Worker loop pulling orders from Redis and dispatching to Nubra UAT."""
        retries = 0
        while self._running:
            try:
                client = _resolve_client(client_pool)
                if not self.redis or client is None:
                    await asyncio.sleep(0.5)
                    continue

                item = await self.redis.brpoplpush(QUEUE_KEY, PROCESSING_KEY, timeout=1)
                if not item:
                    continue
                raw_payload = item if isinstance(item, bytes) else str(item).encode("utf-8")

                try:
                    task = json.loads(raw_payload.decode("utf-8"))
                except Exception:
                    await self._ack(raw_payload)
                    continue
                task_id = task["task_id"]

                await rate_limiter.acquire("general")

                upstream_url = f"{settings.NUBRA_UAT_BASE.rstrip('/')}/{task['path'].lstrip('/')}"
                upstream_headers = {
                    "Authorization": f"Bearer {settings.NUBRA_SESSION_TOKEN}",
                    "x-device-id": settings.NUBRA_DEVICE_ID,
                    "x-device-os": "sdk",
                    "x-app-version": "0.5.4",
                    "Cookie": f"deviceId={settings.NUBRA_DEVICE_ID}",
                    "Accept": "application/json",
                }
                if task.get("content_type"):
                    upstream_headers["Content-Type"] = task["content_type"]

                body = base64.b64decode(task["body_b64"]) if task.get("body_b64") else None

                status_code, content, headers = await self._dispatch_with_retry(
                    client, task["method"], upstream_url, upstream_headers,
                    task.get("query_params", {}), body,
                )

                res_key = f"{RES_KEY_PREFIX}{task_id}"
                res_payload = json.dumps({
                    "status_code": status_code,
                    "content_b64": base64.b64encode(content).decode("ascii"),
                    "headers": {
                        k: v for k, v in headers.items()
                        if k.lower() in ("content-type", "content-encoding", "x-request-id", "retry-after")
                    }
                })

                await self.redis.lpush(res_key, res_payload)
                await self.redis.expire(res_key, 60)
                if task.get("idem_key"):
                    try:
                        await self.redis.set(f"{IDEMPOTENCY_PREFIX}{task['idem_key']}", res_payload, ex=300)
                    except Exception:
                        pass
                await self._ack(raw_payload)
                retries = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[OrderQueue] Error in worker processing loop: {e}")
                retries += 1
                await asyncio.sleep(min(5.0, 0.1 * (2 ** min(retries, 5))))

    async def _dispatch_with_retry(self, client, method, url, headers, params, body,
                                   max_attempts: int = 3):
        last_exc = None
        for attempt in range(max_attempts):
            try:
                resp = await client.request(
                    method=method, url=url, headers=headers,
                    params=params, content=body,
                )
                if resp.status_code == 429 and attempt < max_attempts - 1:
                    retry_after = resp.headers.get("retry-after")
                    try:
                        delay = float(retry_after) if retry_after else 1.0
                    except ValueError:
                        delay = 1.0
                    await asyncio.sleep(min(10.0, max(0.5, delay)))
                    continue
                return resp.status_code, resp.content, dict(resp.headers)
            except Exception as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    await asyncio.sleep(min(5.0, 0.5 * (2 ** attempt)))
        content = json.dumps({
            "status": "error",
            "error_code": "UPSTREAM_GATEWAY_ERROR",
            "message": f"Nubra connection failure: {str(last_exc)}"
        }).encode("utf-8")
        return 502, content, {"content-type": "application/json"}


order_queue = RedisOrderQueue()
