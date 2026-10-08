# Nubra Workshop Relay Adapter (`nubra-workshop-relay`)

Drop-in client adapter for participants of Nubra workshops.

Allows participants to run **official Nubra Python SDK tutorial code** with **zero modifications**, without needing personal Nubra accounts, phone numbers, SMS OTPs, or MPIN prompts.

---

## 🚀 How Students Use This (Zero Repo Cloning Required)

Participants do **NOT** need to clone the repository or download zip files. They just run one pip command:

```bash
pip install git+https://github.com/BlackPool25/nubra-relay-gateway.git#subdirectory=client
```

---

## 📝 Code Usage

### Option A: 1-Line Import at the top of their script (Recommended)

```python
import nubra_patch  # Automatically connects to the live workshop relay

# Now write official Nubra SDK code exactly as taught:
from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
from nubra_python_sdk.refdata.instruments import InstrumentData
from nubra_python_sdk.marketdata.market_data import MarketData

# Initializes instantly without OTP or MPIN prompts!
nubra = InitNubraSdk(NubraEnv.UAT)

# Resolve instruments
instruments = InstrumentData(nubra)
inst = instruments.get_instrument_by_symbol("RELIANCE26OCT700CE", exchange="NSE")
print("Instrument:", inst.stock_name, "RefID:", inst.ref_id)

# Fetch market data
market = MarketData(nubra)
quote = market.quote(ref_id=inst.ref_id, levels=5)
print("LTP:", quote.orderBook.last_traded_price)
```

---

### Option B: Zero Code Edits (Auto-Load via `.pth`)

If the resource person does not want students to write `import nubra_patch` in their Python code at all:

Run this one-liner in their terminal once:
```bash
python -c "import site, os; open(os.path.join(site.getsitepackages()[0], 'nubra_workshop.pth'), 'w').write('import nubra_patch\n')"
```

Now, **every single Python script** in that environment running `InitNubraSdk(NubraEnv.UAT)` will automatically route through the workshop relay gateway without changing a single line of Python code!
