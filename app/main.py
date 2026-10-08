import asyncio
from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.cache import cache_manager
from app.queue import rate_limiter
from app.security import student_registry
from app.proxy import relay_request, init_http_client, close_http_client
from app.order_queue import order_queue
from app.websocket_proxy import proxy_websocket

# Keepalive background ping task to prevent Nubra session timeout
async def session_keepalive_task():
    while True:
        try:
            await asyncio.sleep(600)  # Ping every 10 minutes
            if settings.NUBRA_SESSION_TOKEN and settings.NUBRA_DEVICE_ID:
                from app.proxy import client_pool
                if client_pool:
                    url = f"{settings.NUBRA_UAT_BASE.rstrip('/')}/refdata/refdata/{date.today().isoformat()}"
                    headers = {
                        "Authorization": f"Bearer {settings.NUBRA_SESSION_TOKEN}",
                        "x-device-id": settings.NUBRA_DEVICE_ID,
                        "x-device-os": "sdk",
                        "x-app-version": "0.5.4",
                        "Cookie": f"deviceId={settings.NUBRA_DEVICE_ID}",
                    }
                    resp = await client_pool.get(url, headers=headers, timeout=5.0)
                    print(f"[Keepalive] Session ping status: {resp.status_code}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Keepalive] Ping failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=== Starting Nubra UAT Relay & Queue Gateway ===")
    print(f"Target Nubra Base: {settings.NUBRA_UAT_BASE}")
    print(f"Student Verification Active: {settings.ENABLE_STUDENT_VERIFICATION}")
    print(f"Max Upstream RPS: {settings.MAX_UPSTREAM_RPS}")

    # 1. Initialize Cache & Redis
    await cache_manager.initialize()
    rate_limiter.set_redis(cache_manager.redis)

    # 1b. Initialize Redis order queue on a separate logical DB when possible
    # so LRU cache eviction can never drop pending order jobs.
    if settings.ENABLE_REDIS_QUEUE:
        try:
            import redis.asyncio as aioredis
            queue_url = settings.REDIS_QUEUE_URL or settings.REDIS_URL
            if queue_url and not settings.REDIS_QUEUE_URL:
                base, _, db = queue_url.rpartition("/")
                queue_url = f"{base}/1" if base and db.isdigit() else queue_url
            queue_redis = aioredis.from_url(queue_url, decode_responses=False) if queue_url else None
            if queue_redis is not None:
                await queue_redis.ping()
            if queue_redis is not None and queue_redis is not cache_manager.redis:
                order_queue.set_redis(queue_redis, owns=True)
            else:
                order_queue.set_redis(cache_manager.redis)
        except Exception as exc:
            print(f"[OrderQueue] Queue Redis unavailable, sharing cache redis: {exc}")
            order_queue.set_redis(cache_manager.redis)

    # 2. Initialize HTTP Client Pool
    await init_http_client()

    # 2b. Launch Redis order-queue worker draining POST /sentinel/orders/*
    if settings.ENABLE_REDIS_QUEUE:
        import app.proxy as proxy_mod
        await order_queue.start_worker(lambda: proxy_mod.client_pool)

    # 3. Reload Student Registry
    student_registry.reload()

    # 4. Launch Keepalive Ping Task
    keepalive_handle = asyncio.create_task(session_keepalive_task())

    yield

    # Shutdown
    print("=== Shutting Down Nubra UAT Relay Gateway ===")
    keepalive_handle.cancel()
    await order_queue.stop_worker()
    await close_http_client()
    await cache_manager.close()

app = FastAPI(
    title="Nubra UAT Relay & Queue Gateway",
    description="Drop-in transparent relay for Nubra OMS V3 with request coalescing, queuing, and security controls.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,   # Hide Swagger in production / workshop
    redoc_url=None
)

# Open CORS for workshop tools / browser SDKs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["System"])
async def health_check():
    """Health status endpoint for Docker and monitoring."""
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "service": "nubra-relay-gateway",
            "redis_connected": cache_manager.redis is not None,
            "verification_enabled": settings.ENABLE_STUDENT_VERIFICATION
        }
    )


@app.websocket("/ws")
async def websocket_ticker(websocket: WebSocket):
    await proxy_websocket(websocket, "ws")


@app.websocket("/apibatch/ws")
async def websocket_batch(websocket: WebSocket):
    await proxy_websocket(websocket, "apibatch/ws")


@app.websocket("/oms-socket-latest/ws")
async def websocket_oms(websocket: WebSocket):
    await proxy_websocket(websocket, "oms-socket-latest/ws")

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def catch_all_proxy(request: Request, path: str):
    """
    Transparent catch-all router preserving 100% Nubra REST API v3 schema.
    """
    return await relay_request(request, path)
