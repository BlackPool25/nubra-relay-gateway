# Nubra UAT Relay & Queue Gateway

A transparent, zero-trust relay gateway designed for trading workshops, training bootcamps, and hackathons using the **Nubra Trading API (v3)** in its **UAT sandbox** (`https://uatapi.nubra.io`).

---

## 🌟 Key Features

* **Transparent Drop-in Compatibility:** Students keep 100% standard Nubra headers (`Authorization: Bearer <token>`, `x-device-id: <id>`) and standard request/response JSON schemas. They only change the `BASE_URL`.
* **Zero Session Invalidation:** The gateway is the single authenticated client to Nubra UAT. Students never knock each other offline with HTTP 440 errors.
* **Intelligent Query Caching & Request Coalescing:** Identical requests (quotes, instruments, order books) are served from cache with single-flight locks, preventing redundant upstream calls.
* **Two-Tier Rate Governor (Nubra Matching):** Outbound requests are governed using dual token buckets matching Nubra's official per-IP limits:
  * **Trading & Orders:** **85 ops/sec** (Nubra UAT ceiling: 100 ops/sec).
  * **Historical Data (REST):** **50 req/min** (Nubra ceiling: 60 req/min).
* **Event-Driven Write-Through Cache Invalidation:** Placing, modifying, or cancelling an order immediately purges cached order lists and symbol depth to guarantee zero stale reads.
* **Default-Deny Security Guard:** Automatically blocks sensitive reporting endpoints (`/report/*`, `/userinfo`, `/profile`) and destructive bulk actions (`/trading/exit-all-positions`).
* **Zero-Trust Expose Layer:** Containerized **Tailscale Funnel** exposes a public HTTPS endpoint to the open internet without router port forwarding or DNS setup.
* **Configurable Student Verification Subsystem:** Toggled via `ENABLE_STUDENT_VERIFICATION=false` by default, with structured local registry support when enabled.

---

## 🚀 Quick Start for the Workshop Organizer

### Step 1: Run the Interactive PC Setup Wizard

The interactive setup wizard verifies your Nubra UAT master credentials (via interactive OTP+MPIN terminal login or manual token entry), generates student access tokens, and creates a secure `.env` file:

```bash
cd ~/projects/nubra-relay-gateway
uv run scripts/setup_credentials.py
# (or: python3 scripts/setup_credentials.py)
```

### Step 2: Start the Containers with Tailscale Funnel

Start the isolated containers (Relay + Redis + Tailscale Funnel):
```bash
docker compose up -d
```
The containerized Tailscale service automatically:
1. Connects to your tailnet using `TS_AUTHKEY`.
2. Provisions a public Let's Encrypt certificate.
3. Exposes the gateway publicly to the internet at `https://nubra-relay.<your-tailnet>.ts.net`.

### Step 3: Retrieve the Public Gateway URL

Run the URL detector script to verify the ingress status and extract the public HTTPS link for students:
```bash
uv run scripts/get_gateway_url.py
# (or: python3 scripts/get_gateway_url.py)
```

### Step 4: Run Diagnostics

Verify the gateway is operational, caching correctly, and enforcing route security:
```bash
python3 scripts/test_relay.py
```

---

## 👨‍💻 Student Integration Guide

Provide students with your public gateway URL and their assigned token.

### Python Example (`requests`)

Students use the exact same Nubra V3 endpoints and schemas—they only replace the base URL:

```python
import requests

# 1. Change only the Base URL
BASE_URL = "https://nubra-relay.<your-tailnet>.ts.net"

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

# Place Order (Sentinel OMS V3 Schema — prices are integer paise)
order_payload = {
    "refId": 71878,
    "qty": 1,
    "side": "BUY",
    "deliveryType": "IDAY",
    "priceType": "LIMIT",
    "validityType": "DAY",
    "isMultiLeg": False,
    "executionMode": "ENTRY",
    "entryPrice": 100000,
    "stratTags": ["workshop-trade-01"],  # exactly one hyphenated tag
}

order_resp = requests.post(f"{BASE_URL}/sentinel/orders/create", json=order_payload, headers=headers)
print("Order Placement:", order_resp.json())
```

### Approach B: Using the Official `nubra-sdk` Python Package (`NubraTrader`)

If the workshop assignment requires using Nubra's official Python SDK classes (`NubraTrader`), students can use [`scripts/student_sdk_helper.py`](file:///home/shreyas/projects/nubra-relay-gateway/scripts/student_sdk_helper.py) to initialize `NubraTrader` targeting the relay without needing an OTP or MPIN:

```python
from student_sdk_helper import get_nubra_trader

RELAY_URL = "https://nubra-relay.<your-tailnet>.ts.net"
STUDENT_TOKEN = "STU_TOKEN_01_A8B2"

# Instantiates an authenticated NubraTrader instance directly
trader = get_nubra_trader(RELAY_URL, STUDENT_TOKEN)

# Place orders using official SDK methods (prices are integer paise):
response = trader.create_order({
    "refId": 71878,
    "qty": 1,
    "side": "BUY",
    "deliveryType": "IDAY",
    "priceType": "LIMIT",
    "validityType": "DAY",
    "isMultiLeg": False,
    "executionMode": "ENTRY",
    "entryPrice": 100000,
    "stratTags": ["workshop-trade-01"],  # exactly one hyphenated tag
})
print("Order Response:", response)
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
| `MAX_UPSTREAM_RPS` | `85` | Max requests per second for Trading/Orders (Nubra UAT ceiling: 100 ops/sec) |
| `MAX_HISTORICAL_RPM` | `50` | Max requests per minute for Historical Data (Nubra ceiling: 60 req/min) |
| `ENABLE_CACHE` | `true` | Enables Redis/memory caching layer |
| `CACHE_TTL_INSTRUMENTS` | `3600` | Instrument list cache TTL (1 hour) |
| `CACHE_TTL_ORDERBOOK` | `1.5` | Orderbook / market depth cache TTL (seconds) |
| `CACHE_TTL_QUOTES` | `1.0` | Quote / LTP cache TTL (seconds) |
| `CACHE_TTL_HISTORICAL` | `60.0` | Historical candle data cache TTL (seconds) |
| `TS_AUTHKEY` | *(optional)* | Tailscale Auth Key for public Funnel HTTPS ingress |

---

## 🛡️ Security Architecture

* Detailed architectural specifications, data models, single-flight coalescing design, rate limit calculations, and request flow diagrams are documented in [`docs/DMA_ARCHITECTURE.md`](file:///home/shreyas/projects/nubra-relay-gateway/docs/DMA_ARCHITECTURE.md).
