import json
import httpx
from fastapi import Request, Response, HTTPException, status
from app.config import settings
from app.security import check_path_permission, authenticate_student
from app.cache import cache_manager
from app.queue import rate_limiter

# Reusable HTTP client with persistent connection pooling
client_pool: httpx.AsyncClient = None

async def init_http_client():
    global client_pool
    client_pool = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=30.0),
        limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
        follow_redirects=True
    )

async def close_http_client():
    global client_pool
    if client_pool:
        await client_pool.aclose()

async def relay_request(request: Request, path: str) -> Response:
    # 1. Security & Blacklist Check
    check_path_permission(path)

    # 2. Transparent Student Authentication
    student_id = authenticate_student(request)

    # 3. Cache Evaluation: STRICTLY for GET/HEAD requests only
    is_safe_method = request.method in ("GET", "HEAD")
    body = await request.body()
    query_params = dict(request.query_params)
    cache_key = cache_manager.generate_cache_key(request.method, path, query_params, body) if is_safe_method else None

    if is_safe_method and cache_key:
        cached = await cache_manager.get(cache_key)
        if cached:
            status_code, content, headers = cached
            resp_headers = dict(headers)
            resp_headers["X-Cache"] = "HIT"
            resp_headers["X-Workshop-Student"] = student_id
            return Response(
                content=content,
                status_code=status_code,
                headers=resp_headers,
                media_type=resp_headers.get("content-type", "application/json")
            )

    # 4. Define Fetch Function for Upstream Call
    clean_path = path.lower()
    category = "historical" if "historical" in clean_path else "general"

    async def fetch_upstream():
        # Enforce rate limiter queue matching Nubra limits
        await rate_limiter.acquire(category=category)

        # Build upstream URL
        upstream_url = f"{settings.NUBRA_UAT_BASE.rstrip('/')}/{path.lstrip('/')}"

        # Construct upstream headers
        upstream_headers = {
            "Authorization": f"Bearer {settings.NUBRA_SESSION_TOKEN}",
            "x-device-id": settings.NUBRA_DEVICE_ID,
            "Accept": request.headers.get("Accept", "application/json"),
        }
        if "content-type" in request.headers:
            upstream_headers["Content-Type"] = request.headers["content-type"]

        try:
            resp = await client_pool.request(
                method=request.method,
                url=upstream_url,
                headers=upstream_headers,
                params=query_params,
                content=body if not is_safe_method else None
            )
            return resp.status_code, resp.content, dict(resp.headers)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "status": "error",
                    "error_code": "UPSTREAM_GATEWAY_ERROR",
                    "message": f"Failed communicating with Nubra UAT: {str(exc)}"
                }
            )

    # 5. Dispatch Request: Single-Flight Coalescing for GET; Direct for Mutations
    if is_safe_method and cache_key:
        result = await cache_manager.coalescer.execute_or_wait(cache_key, fetch_upstream)
    else:
        result = await fetch_upstream()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving response from upstream."
        )

    status_code, content, headers = result

    # 6. Post-Processing & Event-Driven Cache Invalidation
    if is_safe_method and cache_key and status_code == 200:
        # Cache successful GET responses
        ttl = cache_manager.get_ttl_for_path(path)
        await cache_manager.set(cache_key, status_code, content, headers, ttl)
    elif not is_safe_method and status_code in (200, 201, 202, 204):
        # A mutating request (POST, PUT, DELETE) succeeded!
        # Perform event-driven invalidation to prevent stale reads
        ref_id = None
        if body:
            try:
                body_json = json.loads(body)
                if isinstance(body_json, dict):
                    ref_id = body_json.get("refId") or body_json.get("ref_id")
            except Exception:
                pass

        clean_path = path.lower()
        if "orders" in clean_path or "funds" in clean_path:
            await cache_manager.invalidate_trade_state(ref_id=ref_id)

    # 7. Return verbatim response to student
    resp_headers = {
        k: v for k, v in headers.items()
        if k.lower() in ("content-type", "content-encoding", "x-request-id", "retry-after")
    }
    resp_headers["X-Cache"] = "MISS" if is_safe_method else "BYPASS"
    resp_headers["X-Workshop-Student"] = student_id

    return Response(
        content=content,
        status_code=status_code,
        headers=resp_headers,
        media_type=resp_headers.get("content-type", "application/json")
    )
