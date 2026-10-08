# nubra_workshop

Drop-in workshop adapter for the official [Nubra Python SDK](https://pypi.org/project/nubra-sdk/).

This package allows workshop participants and students to run **unmodified, official Nubra Python SDK tutorials and examples** without needing individual account signups, phone numbers, SMS OTPs, or MPINs.

---

## 🚀 Quick Start for Students

### 1. Install
```bash
pip install nubra_workshop
```

### 2. Patch explicitly, then run unmodified Nubra code
Write native Nubra SDK code exactly as shown in official Nubra documentation.
Call `apply_patch()` once at startup — this is required (a bare import is not
enough: the `.pth` auto-loader runs before the SDK is importable and cannot
patch on its own; an import hook retries automatically, but explicit is reliable):

```python
import nubra_workshop
nubra_workshop.apply_patch()
assert nubra_workshop.is_active(), nubra_workshop.status()

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

1. **Explicit activation**: call `nubra_workshop.apply_patch()` (idempotent) after
   importing. The `site-packages` auto-loader (`.pth`) attempts this for you, but
   Python runs it before the SDK is importable, so an import hook retries the
   patch when `nubra_python_sdk` is first imported. Verify with
   `nubra_workshop.status()`.
2. **Explicit Import**: include `import nubra_workshop` at the top of your script.
3. **Custom Gateway URL**: If your instructor hosts a custom gateway, point to it using an environment variable:
   ```bash
   export NUBRA_GATEWAY_URL="https://your-custom-gateway.example.com"
   ```

---

## 📦 Compatibility
- Official `nubra-sdk >= 0.5.4`
- Python `>= 3.9`
