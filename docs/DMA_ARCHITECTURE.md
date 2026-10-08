# Data Modelling Architecture (DMA): Nubra UAT Relay & Queue Gateway

---

## 1. Executive Summary & Design Tenets

The **Nubra UAT Relay & Queue Gateway** is a transparent, zero-trust proxy and request governor designed for workshop and training environments. It enables dozens of student developers to interface simultaneously with Nubra's Trading API (v3) in the sandbox environment (`https://uatapi.nubra.io`) without:
1. Triggering session invalidations (HTTP 440) caused by concurrent logins against a single `x-device-id`.
2. Requiring master phone/MPIN credentials to be distributed or entered on participant devices.
3. Exposing sensitive reporting endpoints or account PII (PAN, demat numbers, tax ledgers).
4. Exhausting upstream rate limits (100 ops/sec UAT burst, 60 req/min historical) due to repeated querying by participants.
5. Requiring students to rewrite their trading scripts or SDK headers—the gateway functions as a drop-in replacement by switching only the Base URL.

### Core Architectural Decisions (Aligned with Workshop Requirements)
* **Transparent Nubra Emulation:** Clients authenticate using standard `Authorization: Bearer <token>` and `x-device-id: <device_id>` headers. The gateway validates student identity and swaps in the master Nubra credentials upstream.
* **Pure Upstream Passthrough (Zero Schema Alteration):** Except for blocking forbidden administrative/reporting routes, all request payloads and response bodies are returned with 100% fidelity to Nubra's REST API v3 schema.
* **Intelligent Query Caching & Request Coalescing (Single-Flight):** High-frequency repeated queries (market data, instruments, order books) are served from an in-memory or Redis cache, eliminating redundant network roundtrips to Nubra.
* **Leaky-Bucket Rate Governor:** An asynchronous queue regulates outbound calls to Nubra UAT, keeping aggregate throughput well within safe thresholds.
* **Zero-Trust Expose Layer:** Host-isolated access via **Tailscale Funnel** or **Ngrok**, requiring zero port forwarding on local routers.
* **Configurable Student Verification Subsystem:** Toggled via `ENABLE_STUDENT_VERIFICATION=false` by default, with structured local registry support when active.

---

## 2. High-Level System Architecture & Ingress Flow

```
                                 PARTICIPANT DEVICES (WORKSHOP STUDENTS)
                       ┌────────────────────────────────────────────────────────┐
                       │ Student A (Python SDK / curl)  │ Student B (Script)     │
                       │ Target: https://relay.domain   │ Target: https://relay  │
                       └────────────────────────────┬───────────────────────────┘
                                                    │
                                                    │ HTTPS (Standard Bearer Auth)
                                                    ▼
                       ┌────────────────────────────────────────────────────────┐
                       │           Zero-Trust Tunnel (Tailscale / Ngrok)        │
                       │   - Public TLS Termination                             │
                       │   - Host port forwarding eliminated                    │
                       └────────────────────────────┬───────────────────────────┘
                                                    │
                                                    ▼
 ╔══════════════════════════════════════════════════════════════════════════════════════════╗
 ║                                DOCKER HOST CONTAINER                                     ║
 ║                                                                                          ║
 ║  ┌────────────────────────────────────────────────────────────────────────────────────┐  ║
 ║  │                             Ingress Security Guard                                 │  ║
 ║  │  - Transparent Auth Interceptor (Extracts Bearer token & Device ID)                │  ║
 ║  │  - Blacklist Route Guard (403 for /report, /userinfo, etc.)                        │  ║
 ║  │  - Optional Student Verifier (Enabled when ENABLE_STUDENT_VERIFICATION=true)       │  ║
 ║  └─────────────────────────────────────────┬──────────────────────────────────────────┘  ║
 ║                                            │                                             ║
 ║                      ┌─────────────────────┴─────────────────────┐                       ║
 ║                      ▼                                           ▼                       ║
 ║       [GET Query / Market Data / Instruments]      [POST/PUT/DELETE Trading Orders]      ║
 ║                      │                                           │                       ║
 ║                      ▼                                           ▼                       ║
 ║  ┌───────────────────────────────────────┐   ┌────────────────────────────────────────┐  ║
 ║  │  Intelligent Cache & Single-Flight    │   │      Asynchronous Leaky Bucket         │  ║
 ║  │  - Redis / In-Memory TTLCache         │   │  - Max 80 ops/sec upstream governor    │  ║
 ║  │  - Dynamic coalescing of twin queries │   │  - Request serialisation buffer        │  ║
 ║  └───────────────────┬───────────────────┘   └───────────────────┬────────────────────┘  ║
 ║                      │ (Cache Miss)                              │                       ║
 ║                      └─────────────────────┬─────────────────────┘                       ║
 ║                                            │                                             ║
 ║                                            ▼                                             ║
 ║  ┌────────────────────────────────────────────────────────────────────────────────────┐  ║
 ║  │                            Upstream Dispatcher                                     │  ║
 ║  │  - Injects Master NUBRA_SESSION_TOKEN & NUBRA_DEVICE_ID                            │  ║
 ║  │  - Preserves exact path, query parameters, body encoding                           │  ║
 ║  │  - Returns exact unmodified Nubra response payload to student                      │  ║
 ║  └─────────────────────────────────────────┬──────────────────────────────────────────┘  ║
 ╚════════════════════════════════════════════┼══════════════════════════════════════════════╝
                                              │
                                              │ HTTPS Outbound
                                              ▼
                       ┌────────────────────────────────────────────────────────┐
                       │               Nubra UAT Base Gateway                   │
                       │               https://uatapi.nubra.io                  │
                       └────────────────────────────────────────────────────────┘
```

---

## 3. Transparent Nubra Protocol Emulation

To ensure students experience zero compatibility friction, the gateway operates under **Strict Transparency**.

### 3.1. Client Configuration Comparison

| Configuration Parameter | Direct Nubra Access (Broken for Workshops) | Gateway Access (Workshop Mode) |
| :--- | :--- | :--- |
| **Base URL** | `https://uatapi.nubra.io` | `https://<tunnel-domain>.ngrok-free.app` or `https://<node>.tailscale.net` |
| **Auth Header** | `Authorization: Bearer <session_token>` | `Authorization: Bearer <assigned_student_token>` |
| **Device Header** | `x-device-id: <user_device_id>` | `x-device-id: <assigned_device_id>` *(or any arbitrary string)* |
| **Request Payload** | Standard Nubra V3 JSON | **Unchanged** (Standard Nubra V3 JSON) |
| **Response Payload** | Standard Nubra V3 JSON | **Unchanged** (Standard Nubra V3 JSON) |

### 3.2. Authentication Translation Engine

When a request enters the gateway:
1. `Authorization: Bearer <token>` is intercepted.
2. The gateway verifies the token against the student token registry.
3. If valid, the gateway strips the client's token and injects the host's master credentials:
   ```http
   # Inbound from Student
   Authorization: Bearer STU_ALPHA_9918
   x-device-id: student-macbook-01

   # Outbound to Upstream Nubra
   Authorization: Bearer {{MASTER_NUBRA_SESSION_TOKEN}}
   x-device-id: {{MASTER_NUBRA_DEVICE_ID}}
   ```
4. If invalid, the gateway returns:
   ```json
   {
     "status": "error",
     "error_code": "UNAUTHORIZED",
     "message": "Invalid or missing workshop authorization token."
   }
   ```

---

## 4. Endpoint Routing & Security Matrix

A strict Default-Deny router protects account security while maintaining open access to trading and market data endpoints.

### 4.1. Endpoint Classifications

| Path / Pattern | HTTP Method | Policy | Upstream Action | Caching Strategy |
| :--- | :--- | :--- | :--- | :--- |
| `/report/*` | ANY | **BLOCKED (403)** | Dropped immediately; zero upstream egress | N/A |
| `/profile`, `/userinfo` (upstream) | ANY | **BLOCKED / MOCKED** | `/userinfo` returns relay WS URLs only; never forwards master PII | N/A |
| `/logout` | POST | **MOCKED LOCALLY** | Returns `{"msg": "Logout successful"}`; never forwarded upstream | N/A |
| `/sendphoneotp`, `/verifyphoneotp`, `/verifypin`, `/totp/*`, `/login-insti`, `/api-keys/login`, `/reset_password`, `/ipaddress/*` | ANY | **BLOCKED (403)** | OTP/MPIN flows would invalidate shared session | N/A |
| `/depository/*` | ANY | **BLOCKED (403)** | eDIS/CDSL browser flow is per-account, unsafe shared | N/A |
| `/trading/exit-all-positions`, `/trading/orders/cancel-all` | POST, DELETE | **BLOCKED (403)** | Dropped to prevent mass workshop disruption | N/A |
| `/refdata/refdata/{YYYY-MM-DD}?exchange=NSE\|BSE\|MCX` | GET | **ALLOWED** | Relayed with master credentials | **Cached (1 Hour)** |
| `/orderbooks/{ref_id}?levels=` | GET | **ALLOWED** | Relayed with master credentials | **Cached (1.5 Seconds)** |
| `/optionchains/{asset}`, `/optionchains/{asset}/price` | GET | **ALLOWED** | Relayed with master credentials | **Cached (1 Second)** |
| `/charts/timeseries`, `/charts/multistrike` | POST | **ALLOWED** | Relayed with historical-bucket limiter | **Not cached (POST)** |
| `/screener/fetch_company_fundamentals*` | GET | **ALLOWED** | Relayed with master credentials | **Cached (2 Seconds default)** |
| `/sentinel/orders?intentOrderId=...` | GET | **ALLOWED** | Direct passthrough | **No-Cache** |
| `/sentinel/orders/create`, `/sentinel/orders/modify`, `/sentinel/orders/cancel` | POST | **ALLOWED** | Redis FIFO queue (BRPOPLPUSH + ACK + retry) | **No-Cache** |
| `/sentinel/orders/funds_required` | POST | **ALLOWED** | Direct passthrough | **No-Cache** |
| `/sentinel/portfolio/positions\|holdings\|user_funds_and_margin` | GET | **ALLOWED** | Direct passthrough | **No-Cache** |
| `/sentinel/strategy-portfolio*` | GET/POST/DELETE | **ALLOWED** | Direct passthrough | **No-Cache** |
| `/ws`, `/apibatch/ws`, `/oms-socket-latest/ws` | WS | **ALLOWED** | Bidirectional proxy; student token swapped for master token | N/A |

---

## 5. Nubra REST API v3 Data Models & Schema Reference

The gateway directly supports the canonical Nubra V3 data models. All request and response schemas mirror Nubra's OMS Sentinel standard.

### 5.1. Order Placement Schema (`POST /sentinel/orders/create`)

V3 uses the `orders[]` wrapper with camelCase fields and integer `intentOrderId`
(see `references/nubra-sdk-package/trading/validation.py: CreateIntentOrderRequest`).
Prices are exchange-native integers (paise for NSE).

#### Inbound Request Body
```json
{
  "orders": [
    {
      "refId": 97713,
      "qty": 10,
      "side": "BUY",
      "deliveryType": "IDAY",
      "priceType": "LIMIT",
      "validityType": "DAY",
      "executionMode": "ENTRY",
      "entryPrice": 45050,
      "isMultiLeg": false,
      "stratTags": ["workshop"]
    }
  ]
}
```

#### Field Specifications:
* `orders[]` *(array, required)*: one entry per single order; strategy orders use one entry with `isMultiLeg: true` + `legs[]`.
* `refId` *(integer)*: required for single-leg; absent for multi-leg (legs carry `refId` + `unitQty`).
* `side` *(string)*: `BUY` | `SELL` (multi-leg entry must not be `SELL`).
* `deliveryType` *(string)*: `IDAY` | `CNC`.
* `priceType` *(string)*: `LIMIT` | `MARKET`.
* `validityType` *(string)*: `DAY` | `IOC` | `GTE`.
* `qty` *(integer, required)*: quantity in lots/units.
* `entryPrice` *(integer, optional)*: paise for NSE limit orders.
* `orderId` *(integer, optional)*: strategy-level `intentOrderId` for modify/cancel.
* `stratTags` *(string[])*: hyphen-separated tags only.

#### Upstream Success Response (`200 OK`)
```json
{
  "intentOrderId": 987654,
  "orderStatus": "INTENT_ORDER_STATUS_OPEN"
}
```

---

### 5.2. Order Retrieval Schema (`GET /sentinel/orders`)

#### Response Body (`200 OK`)
V3 returns `{orders: {<bucket>: [...]}}` keyed by status bucket — not `{status, data: [...]}`.
```json
{
  "orders": {
    "open": [
      {
        "intentOrderId": 987654,
        "refId": 97713,
        "orderStatus": "INTENT_ORDER_STATUS_OPEN",
        "orderSide": "BUY",
        "orderQty": 10,
        "filledQty": 0,
        "orderPrice": 45050
      }
    ],
    "executed": [],
    "cancelled": [],
    "rejected": []
  }
}
```

---

### 5.3. Market Depth Schema (`GET /orderbooks/{ref_id}?levels=`)

#### Response Body (`200 OK`)
Field names follow the SDK wrapper (`OrderBookWrapper`): `ref_id`, `last_traded_price`,
`bids[]`/`asks[]` with `{price, quantity, num_orders}`. Prices are paise integers.
```json
{
  "ref_id": 97713,
  "timestamp": 1760364520123,
  "last_traded_price": 45075,
  "last_traded_quantity": 50,
  "volume": 1284500,
  "bids": [
    { "price": 45050, "quantity": 150, "num_orders": 3 }
  ],
  "asks": [
    { "price": 45075, "quantity": 220, "num_orders": 4 }
  ]
}
```

---

## 6. Intelligent Caching & Request Coalescing Architecture

To prevent participants from dogpiling the upstream Nubra API with identical requests (e.g. 20 students querying `/orderbooks/97713` at the same time), the gateway implements a multi-tier caching and coalescing pipeline.

```
                         Incoming Student Requests
                  ┌─────────┐   ┌─────────┐   ┌─────────┐
                  │Student A│   │Student B│   │Student C│
                  └────┬────┘   └────┬────┘   └────┬────┘
                       │             │             │
                       ▼             ▼             ▼
             ┌───────────────────────────────────────────────┐
             │       Cache Key Resolver & Hash Engine        │
             │       Key: HASH(method + path + sorted_params)│
             └───────────────────────┬───────────────────────┘
                                     │
                     ┌───────────────┴───────────────┐
                     │ Check Cache (Redis / In-Mem)  │
                     └───────────────┬───────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │                                 │
              [Cache HIT]                        [Cache MISS]
                    │                                 │
                    ▼                                 ▼
         Return Cached Response        ┌───────────────────────────────┐
         Header: X-Cache: HIT          │     Single-Flight Barrier     │
                                       │    (Lock per distinct Key)    │
                                       └──────────────┬────────────────┘
                                                      │
                                    ┌─────────────────┴─────────────────┐
                                    │ (First Request)   │ (Twin Requests)
                                    ▼                   ▼
                           Upstream Egress Queue   Wait on Async Event
                                    │                   │
                                    ▼                   ▼
                           Store in Cache      Serve newly cached data
```

### 6.1. Single-Flight Coalescing Engine
When multiple concurrent requests experience a cache miss for the same endpoint, the gateway allows **only the first request** to reach the outbound queue. Twin requests await the completion of the in-flight request via an `asyncio.Event` barrier and receive the fresh cache payload instantly, completely eliminating upstream request replication.

### 6.2. Cache Key & TTL Matrix

| Endpoint Type | Cache Key Format | Storage Engine | TTL | Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **Instrument Master** | `nubra_cache:instruments:refdata/...` | Redis / Memory | 3600s (1 hr) | Long-lived static payload |
| **Market Depth / Orderbook**| `nubra_cache:ref:{refId}:orderbooks/...` | Redis / Memory | 1.5s | Micro-cache with single-flight |
| **Quotes / Option Chain** | `nubra_cache:ref:{refId}:optionchains/...` or `gen:{hash}` | Redis / Memory | 1.0s | Micro-cache |
| **Historical Candles** | `nubra_cache:gen:{hash}` (`charts/*`, POST never cached) | Redis / Memory | 60.0s | Medium-lived idempotent query |
| **Active Orders / Portfolio / Strategy** | No-cache passthrough | N/A | 0s | Always live; never stored |
| **Margin Estimation** | `nubra_cache:funds:{hash}` | Redis / Memory | 15.0s | Purged on trade mutation |

### 6.3. Strict Mutation Policy (POST/PUT/DELETE Never Cached)
Under RFC 9111 HTTP caching rules and financial OMS integrity requirements:
* All non-idempotent or state-mutating requests (`POST`, `PUT`, `PATCH`, `DELETE`) **bypass the cache entirely**.
* Every mutating request is processed live through the upstream rate governor directly to Nubra UAT.
* Responses to mutating requests are stamped with header `X-Cache: BYPASS`.

### 6.4. Event-Driven Write-Through Cache Invalidation
When a participant executes an order placement (`POST /sentinel/orders/create`), order modification, or cancellation:
1. The gateway captures the upstream response.
2. If status is `2xx Success`:
   - Extracts the instrument identifier (`refId`) from the request payload.
   - **Immediately purges all order caches** (`nubra_cache:orders*`) so subsequent `GET /sentinel/orders` calls reflect the newly created or modified order without delay.
   - **Purges all funds/margin caches** (`nubra_cache:funds*`) since available collateral has changed.
   - **Purges orderbook depth cache** (`nubra_cache:ref:{refId}*`) for the affected symbol so level 2 book depth refreshes immediately.

---

## 7. Asynchronous Outbound Rate Governor (Nubra Matching Model)

Upstream Nubra limits are enforced per IP address. The gateway models outbound egress through a **Two-Tier Dual-Bucket Rate Governor** matching Nubra's official rate limit tiers:

### 7.1. Official Limit Specifications vs Gateway Enforcement

| Endpoint Category | Official Nubra Ceiling | Gateway Regulated Target | Safety Buffer | Algorithmic Backing |
| :--- | :--- | :--- | :--- | :--- |
| **Trading & General APIs** | **100 ops/sec** per IP | **85 ops/sec** (`MAX_UPSTREAM_RPS`) | 15% Headroom | Token Bucket (`rate_limit:upstream:general`) |
| **Historical Data (REST)** | **60 req/min** per IP | **50 req/min** (`MAX_HISTORICAL_RPM`) | 10 req/min Headroom | Leaky Bucket (`rate_limit:upstream:historical`) |
| **Market Data WebSockets** | Tiered Weight System | N/A (REST Relay Layer) | N/A | N/A |

### 7.2. Dual-Bucket Architecture & Route Classification
Incoming requests are classified before reaching the egress queue:
```
Inbound Request ──► [Path Inspection] ──┬──► /historical-data/*, /charts/* ──► [Tier 2: 50 req/min Bucket] ──► Upstream Nubra
                                         └──► All Other Routes  ──► [Tier 1: 85 ops/sec Bucket]  ──► Upstream Nubra
```

* **Tier 1 (Trading & Orders):** Governs `POST /sentinel/orders/*`, market depth, quotes, and instruments at a peak throughput of **85 ops/sec**, providing sub-millisecond execution while preventing 429 threshold breaches.
* **Tier 2 (Historical Data):** Governs backtesting and historical candle queries at **50 req/min** (approx. 0.83 req/sec), insulating the host IP from Nubra's strict per-minute backtesting limit.

### 7.3. Storage Engines & 429 Backoff Resilience
* **Distributed Redis Token Bucket:** Utilizes Redis `EVAL` with atomic Lua scripts to maintain token count and replenish tokens smoothly across worker threads.
* **Local In-Memory Fallback:** When Redis is offline, seamlessly engages `LocalTokenBucket` instances with micro-sleep intervals.
* **Upstream 429 & Retry-After Handling:** Direct passthrough retries once after honoring `Retry-After` via `rate_limiter.penalize()`; the queue worker retries 429s with backoff. `Retry-After` is relayed to clients in response headers.

---

## 8. Student Verification Infrastructure

The student verification system is decoupled via environment variables.

### 8.1. Configuration Flag
```env
# Set to 'false' for simple token validation (default for workshops)
# Set to 'true' to enforce student registration checks
ENABLE_STUDENT_VERIFICATION=false
```

### 8.2. Verification Schema (`students.json`)
```json
{
  "students": [
    {
      "student_id": "stu_01",
      "name": "Alex Kumar",
      "token": "STU_TOKEN_ALPHA_101",
      "status": "ACTIVE",
      "metadata": {
        "workstation": "WS-01",
        "email": "alex@example.com"
      }
    },
    {
      "student_id": "stu_02",
      "name": "Priya Sharma",
      "token": "STU_TOKEN_BRAVO_202",
      "status": "ACTIVE",
      "metadata": {
        "workstation": "WS-02",
        "email": "priya@example.com"
      }
    }
  ]
}
```

When `ENABLE_STUDENT_VERIFICATION=true`:
1. Request token must match an active student record.
2. If `status != "ACTIVE"`, request is rejected with `401 Unauthorized` (`INVALID_TOKEN`).
3. No per-student rate limits are enforced — upstream buckets are shared globally.

When `ENABLE_STUDENT_VERIFICATION=false` (Default):
1. Any token conforming to the configured workshop prefix or in `.env` `ALLOWED_STUDENT_TOKENS` is admitted immediately.

---

## 9. Zero-Trust Ingress Layer: Tailscale Funnel vs. Ngrok

### 9.1. Comparison Matrix for Workshop Deployments

| Evaluation Criteria | Tailscale Funnel (Official Container) | Ngrok (Containerized Sidecar) | Cloudflare Quick Tunnel (TryCloudflare) |
| :--- | :--- | :--- | :--- |
| **Student Experience** | **Best:** Clean `*.ts.net` HTTPS URL, zero interstitial warnings, pure API passthrough | **Fair:** API requests work, but free web requests hit HTML interstitial warning page | **Excellent:** Clean `*.trycloudflare.com` HTTPS URL, no warning page |
| **Request / Bandwidth Limits** | **Unlimited:** No bandwidth or operations cap from Tailscale | **Restricted:** Free tier capped at 20,000 req/month or 1GB bandwidth | **Unlimited:** Free with no arbitrary monthly request limits |
| **Host Setup Complexity** | **Low-Medium:** Requires free Tailscale Auth Key (`TS_AUTHKEY`) + Funnel enabled in ACL | **Very Low:** Requires single free token (`NGROK_AUTHTOKEN`) in `.env` | **Zero:** No account, no token, no signup required |
| **Public Accessibility** | Public to entire internet (students need **no** Tailscale software) | Public to entire internet | Public to entire internet |
| **Docker Compose Integration** | Native `tailscale/tailscale:latest` container with `serve.json` | Native `ngrok/ngrok:latest` container | Native `cloudflare/cloudflared:latest` container |

### 9.2. Containerized Tailscale Funnel Architecture

The gateway runs the official `tailscale/tailscale:latest` container alongside the relay:
* **Headless Authentication:** Uses an unprivileged, ephemeral or reusable Auth Key (`TS_AUTHKEY`) generated from the Tailscale Admin Console.
* **Persistent Node State:** Node credentials and WireGuard state are preserved in a Docker named volume (`tailscale_state:/var/lib/tailscale`), preventing re-authentication loops on container restarts.
* **Declarative Funnel Routing (`serve.json`):**
  ```json
  {
    "TCP": { "443": { "HTTPS": true } },
    "Web": {
      "${TS_CERT_DOMAIN}:443": {
        "Handlers": { "/": { "Proxy": "http://relay:8000" } }
      }
    },
    "AllowFunnel": { "${TS_CERT_DOMAIN}:443": true }
  }
  ```

---

## 10. PC Host Onboarding & Docker Isolation Workflow

To protect master credentials on the host PC:
1. **Interactive Host Script (`scripts/setup_credentials.py`):**
   * Prompts the workshop organizer for Nubra UAT `session_token`, `x-device-id`, and optional `TS_AUTHKEY`.
   * Performs an immediate pre-flight connectivity check to `https://uatapi.nubra.io/refdata/refdata/{today}?exchange=NSE` to verify token validity before starting containers.
   * Generates student tokens and writes an isolated `.env` file with restrictive file permissions (`chmod 600`).
2. **Container Isolation:**
   * Relay container runs under an unprivileged user (`appuser`, UID 1000).
   * Host network is NOT shared; traffic is strictly bridged via internal Docker networks.
   * Only the zero-trust tunnel service publishes public ingress.
