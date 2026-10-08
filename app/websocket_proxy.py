import asyncio
import re
from fastapi import WebSocket, WebSocketDisconnect
import websockets
try:
    from websockets.exceptions import InvalidStatus as _WsInvalidStatus
except ImportError:
    _WsInvalidStatus = Exception
try:
    from websockets.exceptions import InvalidStatusCode as _WsInvalidStatusCode
except ImportError:
    _WsInvalidStatusCode = Exception
from app.config import settings
from app.security import student_registry, extract_client_token

async def proxy_websocket(websocket: WebSocket, path: str):
    """
    Transparent bidirectional WebSocket proxy for Nubra streaming connections:
    - /ws (Ticker Stream)
    - /apibatch/ws (Protobuf Market Data Batch Ticker)
    - /oms-socket-latest/ws (Realtime Order Updates)

    Translates student authentication on subscription to the master Nubra session token.
    """
    # 1. Authenticate WebSocket Client (from query params, header, or cookie)
    query_params = dict(websocket.query_params)
    token = (
        query_params.get("token")
        or query_params.get("session_token")
        or websocket.headers.get("Authorization", "").replace("Bearer ", "").strip()
        or websocket.cookies.get("token")
    )

    if not token:
        # Check if any default workshop token was provided in header
        auth_hdr = websocket.headers.get("authorization")
        if auth_hdr and auth_hdr.startswith("Bearer "):
            token = auth_hdr[7:].strip()

    # 1b. Validate student token only if student verification is explicitly enabled
    if settings.ENABLE_STUDENT_VERIFICATION:
        if not token or not student_registry.verify_token(token)[0]:
            await websocket.close(code=4401, reason="Unauthorized student token")
            return

    # 2. Accept client connection
    await websocket.accept()

    # 3. Construct Upstream Nubra WebSocket URL
    # Master session token is always used upstream.
    clean_path = path.lstrip("/")
    upstream_ws_url = f"{settings.NUBRA_UAT_WS_BASE.rstrip('/')}/{clean_path}"
    # OMS sockets require ?token=<master_session> on connect.
    if clean_path.startswith("oms-socket-latest"):
        sep = "&" if "?" in upstream_ws_url else "?"
        upstream_ws_url = f"{upstream_ws_url}{sep}token={settings.NUBRA_SESSION_TOKEN}"

    upstream_headers = {
        "Authorization": f"Bearer {settings.NUBRA_SESSION_TOKEN}",
        "x-device-id": settings.NUBRA_DEVICE_ID,
        "User-Agent": "Nubra-Workshop-Relay-Gateway/1.0",
    }

    try:
        async with websockets.connect(
            upstream_ws_url,
            additional_headers=upstream_headers,
            ping_interval=20,
            ping_timeout=10,
            max_size=10 * 1024 * 1024  # 10MB message ceiling for large Protobuf bursts
        ) as upstream_ws:
            print(f"[WebSocket] Connected client to upstream {upstream_ws_url}")

            async def client_to_upstream():
                """Forwards subscriptions from student to Nubra, substituting master token."""
                try:
                    while True:
                        msg = await websocket.receive()
                        if "text" in msg and msg["text"]:
                            text_data = msg["text"].strip()
                            parts = text_data.split(maxsplit=2)
                            cmd = parts[0].lower() if parts else ""
                            
                            # Market-data batch syntax: batch_subscribe [token] <payload>
                            if cmd in ("batch_subscribe", "batch_unsubscribe") and len(parts) >= 2:
                                # Check if second word looks like a known action or token
                                known_batch_keywords = ("orderbook_depth", "post_market", "option", "index_bucket", "socket_interval", "trade", "ohlcv")
                                if parts[1] in known_batch_keywords or parts[1].startswith("{"):
                                    # Student omitted token entirely: batch_subscribe <keyword> ...
                                    text_data = f"{parts[0]} {settings.NUBRA_SESSION_TOKEN} " + " ".join(parts[1:])
                                else:
                                    # Student included a placeholder/student token: replace it
                                    rest = parts[2] if len(parts) > 2 else ""
                                    text_data = f"{parts[0]} {settings.NUBRA_SESSION_TOKEN} {rest}".strip()

                            # OMS order/portfolio syntax: subscribe [token] <channel> <event>
                            elif cmd in ("subscribe", "unsubscribe") and len(parts) >= 2:
                                known_channels = ("direct_intent", "direct_portfolio")
                                if parts[1] in known_channels:
                                    # Student omitted token: subscribe direct_intent notification
                                    text_data = f"{parts[0]} {settings.NUBRA_SESSION_TOKEN} " + " ".join(parts[1:])
                                else:
                                    # Student included dummy/student token: replace it
                                    rest = parts[2] if len(parts) > 2 else ""
                                    text_data = f"{parts[0]} {settings.NUBRA_SESSION_TOKEN} {rest}".strip()

                            await upstream_ws.send(text_data)
                        elif "bytes" in msg and msg["bytes"]:
                            await upstream_ws.send(msg["bytes"])
                except (WebSocketDisconnect, websockets.ConnectionClosed):
                    pass
                except Exception as e:
                    print(f"[WebSocket] Client to upstream error: {e}")

            async def upstream_to_client():
                """Forwards market data ticks and Protobuf messages back to student."""
                try:
                    while True:
                        data = await upstream_ws.recv()
                        if isinstance(data, bytes):
                            await websocket.send_bytes(data)
                        else:
                            await websocket.send_text(data)
                except (WebSocketDisconnect, websockets.ConnectionClosed):
                    pass
                except Exception as e:
                    print(f"[WebSocket] Upstream to client error: {e}")

            # Run both bidirectional loops concurrently
            await asyncio.gather(
                client_to_upstream(),
                upstream_to_client(),
                return_exceptions=True
            )

    except (_WsInvalidStatus, _WsInvalidStatusCode) as e:
        code = getattr(e, "status_code", "unknown")
        print(f"[WebSocket] Upstream connection rejected: {code}")
        try:
            await websocket.close(code=4502, reason=f"Upstream rejected with code {code}")
        except Exception:
            pass
    except Exception as e:
        print(f"[WebSocket] Upstream connection failed: {e}")
        try:
            await websocket.close(code=4502, reason="Upstream connection failed")
        except Exception:
            pass
