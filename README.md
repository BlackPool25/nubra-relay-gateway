# Nubra UAT Relay & Queue Gateway

A transparent, zero-trust relay gateway designed for trading workshops, training bootcamps, and hackathons using the **Nubra Trading API (v3)** in its **UAT sandbox** (`https://uatapi.nubra.io`).

---

## 🌟 Key Features

* **Transparent Drop-in Compatibility:** Students keep 100% standard Nubra headers (`Authorization: Bearer <token>`, `x-device-id: <id>`) and standard request/response JSON schemas. They only change the `BASE_URL`.
* **Zero Session Invalidation:** The gateway is the single authenticated client to Nubra UAT. Students never knock each other offline with HTTP 440 errors.
* **Intelligent Query Caching & Request Coalescing:** Identical requests (quotes, instruments, order books) are served from cache with single-flight locks, preventing redundant upstream calls.
* **Asynchronous Leaky-Bucket Governor:** Outbound requests are governed at a configurable rate (default: 75 req/s) to prevent upstream HTTP 429 rate limit errors.
* **Default-Deny Security Guard:** Automatically blocks sensitive reporting endpoints (`/report/*`, `/userinfo`, `/profile`) and destructive bulk actions (`/trading/exit-all-positions`).
* **Zero-Trust Expose Layer:** Works with **Tailscale Funnel** or **Ngrok** without any router port forwarding or DNS configuration.
* **Configurable Student Verification Subsystem:** Toggled via `ENABLE_STUDENT_VERIFICATION=false` by default, with structured local registry support when enabled.

---

## 🚀 Quick Start for the Workshop Organizer

### Step 1: Run the Interactive PC Setup Wizard

The interactive setup wizard verifies your Nubra UAT master credentials, generates student access tokens, and creates a secure `.env` file:

```bash
cd ~/projects/nubra-relay-gateway
python3 scripts/setup_credentials.py
```

### Step 2: Start the Containers with Tailscale Funnel

Start the containers (Relay + Redis + Tailscale Funnel):
```bash
docker compose up -d
```
The containerized Tailscale service automatically:
1. Connects to your tailnet using `TS_AUTHKEY`.
2. Provisions a public Let's Encrypt certificate.
3. Exposes the gateway publicly at `https://nubra-relay.<your-tailnet>.ts.net`.

### Step 3: Run Diagnostics

Verify the gateway is operational and caching correctly:
```bash
python3 scripts/test_relay.py
```

---

## 👨‍💻 Student Integration Guide

Provide students with your public gateway URL and their assigned token.

### Python Example (`requests`)

Students use the exact same Nubra V3 endpoints and schemas:

```python
import requests

# 1. Change only the Base URL
BASE_URL = "https://your-tunnel-subdomain.ngrok-free.app"  # or Tailscale Funnel URL

# 2. Use standard Nubra Bearer header with assigned student token
headers = {
    "Authorization": "Bearer STU_TOKEN_01_A8B2",
    "x-device-id": "student-laptop-01",
    "Content-Type": "application/json"
}

# Fetch Market Instruments (Served instantly from cache)
instruments = requests.get(f"{BASE_URL}/instruments", headers=headers)
print("Instruments:", instruments.json())

# Fetch Market Depth
orderbook = requests.get(f"{BASE_URL}/orderbooks/97713", headers=headers)
print("Orderbook:", orderbook.json())

# Place Order (Sentinel OMS V3 Schema)
order_payload = {
    "refId": 97713,
    "transactionType": "TRANSACTION_TYPE_BUY",
    "orderType": "ORDER_TYPE_LIMIT",
    "deliveryType": "ORDER_DELIVERY_TYPE_IDAY",
    "validityType": "ORDER_VALIDITY_TYPE_DAY",
    "unitQty": 10,
    "entryPrice": 450.50,
    "intentOrderId": "trade_student_01"
}

order_resp = requests.post(f"{BASE_URL}/sentinel/orders/create", json=order_payload, headers=headers)
print("Order Placement:", order_resp.json())
```

---

## ⚙️ Configuration Reference (`.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `NUBRA_UAT_BASE` | `https://uatapi.nubra.io` | Upstream Nubra UAT sandbox base URL |
| `NUBRA_SESSION_TOKEN` | *(required)* | Master session token from your Nubra account |
| `NUBRA_DEVICE_ID` | *(required)* | Master device ID tied to the session token |
| `ENABLE_STUDENT_VERIFICATION` | `false` | When true, validates students against `students.json` |
| `ALLOWED_STUDENT_TOKENS` | `STU_TOKEN_ALPHA,...` | Comma-separated list of allowed student tokens |
| `MAX_UPSTREAM_RPS` | `75` | Maximum requests per second egress to Nubra |
| `ENABLE_CACHE` | `true` | Enables Redis/memory caching layer |
| `CACHE_TTL_INSTRUMENTS` | `3600` | Instrument list cache TTL (1 hour) |
| `CACHE_TTL_ORDERBOOK` | `1.5` | Orderbook / market depth cache TTL (seconds) |
| `CACHE_TTL_QUOTES` | `1.0` | Quote / LTP cache TTL (seconds) |

---

## 🛡️ Security Architecture

* Detailed architectural specifications, data models, single-flight coalescing design, and request flow diagrams are documented in [`docs/DMA_ARCHITECTURE.md`](file:///home/shreyas/projects/nubra-relay-gateway/docs/DMA_ARCHITECTURE.md).
