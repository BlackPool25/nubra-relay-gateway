import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.cache import cache_manager
from app.queue import rate_limiter
from app.security import student_registry
from app.proxy import relay_request, init_http_client, close_http_client

# Keepalive background ping task to prevent Nubra session timeout
async def session_keepalive_task():
    while True:
        try:
            await asyncio.sleep(600)  # Ping every 10 minutes
            if settings.NUBRA_SESSION_TOKEN and settings.NUBRA_DEVICE_ID:
                from app.proxy import client_pool
                if client_pool:
                    url = f"{settings.NUBRA_UAT_BASE.rstrip('/')}/instruments"
                    headers = {
                        "Authorization": f"Bearer {settings.NUBRA_SESSION_TOKEN}",
                        "x-device-id": settings.NUBRA_DEVICE_ID,
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

    # 2. Initialize HTTP Client Pool
    await init_http_client()

    # 3. Reload Student Registry
    student_registry.reload()

    # 4. Launch Keepalive Ping Task
    keepalive_handle = asyncio.create_task(session_keepalive_task())

    yield

    # Shutdown
    print("=== Shutting Down Nubra UAT Relay Gateway ===")
    keepalive_handle.cancel()
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

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def catch_all_proxy(request: Request, path: str):
    """
    Transparent catch-all router preserving 100% Nubra REST API v3 schema.
    """
    return await relay_request(request, path)
