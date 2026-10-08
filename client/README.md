# nubra_workshop

Drop-in workshop adapter for the official [Nubra Python SDK](https://pypi.org/project/nubra-sdk/).

This package allows workshop participants and students to run **unmodified, official Nubra Python SDK tutorials and examples** without needing individual account signups, phone numbers, SMS OTPs, or MPINs.

---

## 🚀 Quick Start for Students

### 1. Install
```bash
pip install nubra_workshop
```

### 2. Run Unmodified Nubra Code!
Write native Nubra SDK code exactly as shown in official Nubra documentation:

```python
from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
from nubra_python_sdk.refdata.instruments import InstrumentData
from nubra_python_sdk.marketdata.market_data import MarketData

# Initializes via the workshop relay gateway automatically:
nubra = InitNubraSdk(NubraEnv.UAT)

# Fetch instruments:
instruments = InstrumentData(nubra)
inst = instruments.get_instrument_by_symbol("RELIANCE26OCT700CE", exchange="NSE")
print("Found instrument:", inst.stock_name if inst else "None")

# Live market data:
market = MarketData(nubra)
price_info = market.current_price("NIFTY")
print("Live NIFTY Price:", price_info.price if price_info else "N/A")
```

No OTP prompts, no MPIN prompts, and no custom code required!

---

## ⚙️ How It Works

1. **Automatic Initialization**: During `pip install`, `nubra_workshop` registers an auto-loader in Python's `site-packages`. When your script runs `InitNubraSdk`, it routes through the designated workshop relay gateway.
2. **Explicit Import (Optional)**: If you prefer explicit imports, you can include `import nubra_workshop` or `import nubra_patch` at the top of your script.
3. **Custom Gateway URL**: If your instructor hosts a custom gateway, point to it using an environment variable:
   ```bash
   export NUBRA_GATEWAY_URL="https://your-custom-gateway.example.com"
   ```

---

## 📦 Compatibility
- Official `nubra-sdk >= 0.5.4`
- Python `>= 3.9`
