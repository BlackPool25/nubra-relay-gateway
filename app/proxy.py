import json
import httpx
from fastapi import Request, Response, HTTPException, status
from app.config import RELAYED_RESPONSE_HEADERS, settings
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


def _is_queued_order_write(method: str, path: str) -> bool:
    if not settings.ENABLE_REDIS_QUEUE or method.upper() not in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    clean = "/" + path.lower().lstrip("/")
    return clean.startswith("/sentinel/orders")


def _retry_after_seconds(value) -> float:
    try:
        return max(0.5, min(10.0, float(value))) if value is not None else 1.0
    except (TypeError, ValueError):
        return 1.0


def _extract_ref_ids(body: bytes) -> list:
    """Collect refIds from flat, orders[], and legs[] V3 payload shapes."""
    found: list = []
    if not body:
        return found
    try:
        data = json.loads(body)
    except Exception:
        return found
    candidates = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
    stack = list(candidates)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key in ("refId", "ref_id"):
                if node.get(key) is not None:
                    found.append(node[key])
            for key in ("orders", "legs"):
                items = node.get(key)
                if isinstance(items, list):
                    stack.extend(items)
        elif isinstance(node, list):
            stack.extend(node)
    seen = []
    for r in found:
        if r not in seen:
            seen.append(r)
    return seen


def map_oms_disabled_response(status_code: int, content: bytes):
    """Remap upstream 'OMS v2 is not enabled' 403s to a workshop-friendly error.

    Returns (status_code, content) with an explanatory body when the upstream
    rejected a trading/portfolio call for a non-OMS account, else None.
    Status code is preserved so existing callers/tests are unaffected.
    """
    if status_code != 403 or not content:
        return None
    try:
        text = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
    except Exception:
        return None
    if "oms v2 is not enabled" not in text.lower():
        return None
    body = json.dumps({
        "status": "error",
        "error_code": "OMS_DISABLED_UPSTREAM",
        "message": (
            "Upstream Nubra rejected this trading/portfolio call: OMS is not "
            "enabled for the relay account. Market data is unaffected. Ask the "
            "workshop organizer to enable OMS on the master UAT account."
        ),
        "upstream_status": 403,
        "upstream_body": text[:500],
    })
    return status_code, body.encode("utf-8")


async def _dispatch_via_queue(request, path: str, student_id: str, query_params: dict, body: bytes):
    try:
        from app.order_queue import order_queue
        headers = {"content-type": request.headers.get("content-type", "application/json")}
        return await order_queue.enqueue_and_wait(
            method=request.method,
            path=path,
            student_id=student_id,
            query_params=query_params,
            body=body,
            headers=headers,
            timeout=float(settings.QUEUE_TIMEOUT_SECONDS),
        )
    except Exception as exc:
        print(f"[Proxy] Queue dispatch failed, falling back to direct: {exc}")
        return None

async def relay_request(request: Request, path: str) -> Response:
    # 1. Security & Blacklist Check
    check_path_permission(path)

    # 2. Transparent Student Authentication
    student_id = authenticate_student(request)

    # 2b. Safe-intercept session endpoints: NEVER forward master token.
    # Student logout must only clear local state, never kill shared UAT session.
    clean = "/" + path.lower().lstrip("/").split("?")[0]
    if request.method == "POST" and (clean == "/logout" or clean.endswith("/logout")):
        return Response(
            content=json.dumps({"msg": "Logout successful"}),
            status_code=200,
            headers={"content-type": "application/json", "X-Workshop-Student": student_id},
            media_type="application/json",
        )
    if request.method == "GET" and (clean == "/userinfo" or clean.endswith("/userinfo")):
        base = str(request.base_url).rstrip("/")
        ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
        return Response(
            content=json.dumps({
                "message": "workshop session",
                "student_id": student_id,
                "env_info": {
                    "user_ws_url": f"{ws_base}/ws",
                    "market_ws_url": f"{ws_base}/apibatch/ws",
                    "order_service_ws_url": f"{ws_base}/oms-socket-latest/ws",
                },
            }),
            status_code=200,
            headers={"content-type": "application/json", "X-Workshop-Student": student_id},
            media_type="application/json",
        )

    # 3. Cache Evaluation: STRICTLY for GET/HEAD requests only, never for
    # live trading/portfolio state (orders, positions, holdings, strategy).
    is_safe_method = request.method in ("GET", "HEAD")
    no_cache = cache_manager.is_no_cache_path(path)
    body = await request.body()
    query_params = dict(request.query_params)
    cache_key = (cache_manager.generate_cache_key(request.method, path, query_params, body)
                 if (is_safe_method and not no_cache) else None)

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
    category = "historical" if ("historical" in clean_path or "charts/" in clean_path) else "general"

    async def fetch_upstream():
        # Enforce rate limiter queue matching Nubra limits, retry once on 429
        # honoring Retry-After so bursts back off instead of failing students.
        await rate_limiter.acquire(category=category)

        # Build upstream URL
        upstream_url = f"{settings.NUBRA_UAT_BASE.rstrip('/')}/{path.lstrip('/')}"

        # Construct upstream headers
        upstream_headers = {
            "Authorization": f"Bearer {settings.NUBRA_SESSION_TOKEN}",
            "x-device-id": settings.NUBRA_DEVICE_ID,
            "x-device-os": "sdk",
            "x-app-version": "0.5.4",
            "Cookie": f"deviceId={settings.NUBRA_DEVICE_ID}",
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
            if resp.status_code == 429:
                delay = _retry_after_seconds(resp.headers.get("retry-after"))
                await rate_limiter.penalize(category=category, delay=delay)
                await rate_limiter.acquire(category=category)
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

    # 5. Dispatch Request: Single-Flight Coalescing for GET; Queue for order writes; Direct otherwise
    if is_safe_method and cache_key:
        result = await cache_manager.coalescer.execute_or_wait(cache_key, fetch_upstream)
    elif not is_safe_method and _is_queued_order_write(request.method, path):
        result = await _dispatch_via_queue(request, path, student_id, query_params, body)
        if result is None:
            result = await fetch_upstream()
    else:
        result = await fetch_upstream()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving response from upstream."
        )

    status_code, content, headers = result

    # Workshop-friendly mapping for upstream OMS-disabled rejections.
    mapped = map_oms_disabled_response(status_code, content)
    if mapped is not None:
        status_code, content = mapped

    # 6. Post-Processing & Event-Driven Cache Invalidation
    if is_safe_method and cache_key and status_code == 200:
        # Cache successful GET responses
        ttl = cache_manager.get_ttl_for_path(path)
        await cache_manager.set(cache_key, status_code, content, headers, ttl)
    elif not is_safe_method and status_code in (200, 201, 202, 204):
        # A mutating request (POST, PUT, DELETE) succeeded!
        # Perform event-driven invalidation to prevent stale reads
        ref_ids = _extract_ref_ids(body)

        clean_path = path.lower()
        if "orders" in clean_path or "funds" in clean_path or "portfolio" in clean_path:
            await cache_manager.invalidate_trade_state(ref_ids=ref_ids)

    # 7. Return verbatim response to student
    # httpx decodes upstream bodies, so content-encoding must not be re-advertised.
    resp_headers = {
        k: v for k, v in headers.items()
        if k.lower() in RELAYED_RESPONSE_HEADERS
    }
    resp_headers["X-Cache"] = "BYPASS" if (no_cache or not is_safe_method) else "MISS"
    resp_headers["X-Workshop-Student"] = student_id

    return Response(
        content=content,
        status_code=status_code,
        headers=resp_headers,
        media_type=resp_headers.get("content-type", "application/json")
    )
