#!/usr/bin/env python3
"""
Official Nubra Project Example for Workshop Students
Demonstrates 100% native Nubra Python SDK usage (InstrumentData, MarketData, NubraTrader)
routed transparently through the Nubra Workshop Relay Gateway.
"""

import sys
import os

# Add scripts directory to path if running from repo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

# 1. Drop-in patch: routes native SDK to workshop relay without phone/OTP/MPIN prompts
import nubra_patch

# 2. Resource Person's Exact Planned Code:
from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv
from nubra_python_sdk.refdata.instruments import InstrumentData
from nubra_python_sdk.marketdata.market_data import MarketData
from nubra_python_sdk.trading.trading_data import NubraTrader

def main():
    print("==========================================================")
    print("      Native Nubra SDK Workshop Demo (Drop-in Test)       ")
    print("==========================================================\n")

    # Step 1: Initialize SDK (Unmodified Nubra syntax)
    print("[1] Initializing Nubra SDK client...")
    nubra = InitNubraSdk(NubraEnv.UAT)
    print("    ✓ Client initialized successfully (Zero login prompts!)\n")

    # Step 2: Fetch Instrument Reference Data
    print("[2] Resolving NSE stock instrument via InstrumentData...")
    instruments = InstrumentData(nubra)
    symbol = "RELIANCE26OCT700CE"
    inst = instruments.get_instrument_by_symbol(symbol, exchange="NSE")
    if inst:
        print(f"    ✓ Found Instrument: {inst.stock_name} (RefID: {inst.ref_id}, Lot Size: {inst.lot_size})\n")
    else:
        print(f"    ✗ Could not resolve symbol {symbol}\n")
        return

    # Step 3: Fetch Live Market Depth Quote
    print("[3] Fetching 5-level market depth via MarketData...")
    market = MarketData(nubra)
    quote = market.quote(ref_id=inst.ref_id, levels=5)
    if quote and quote.orderBook:
        ob = quote.orderBook
        print(f"    ✓ LTP: {ob.last_traded_price} | Total Volume: {ob.volume}")
        print(f"    ✓ Top Bids: {len(ob.bid or [])} | Top Asks: {len(ob.ask or [])}\n")

    # Step 4: Fetch Live Underlying Option Price
    print("[4] Fetching Underlying NIFTY Option Price...")
    price_info = market.current_price("NIFTY")
    if price_info:
        print(f"    ✓ Underlying: {price_info.exchange} {price_info.message}")
        print(f"    ✓ Current Price: {price_info.price} (Prev Close: {price_info.prev_close})\n")

    # Step 5: Trade Order Operations via NubraTrader
    print("[5] Interacting with OMS via NubraTrader...")
    trader = NubraTrader(client=nubra)
    try:
        orders = trader.orders()
        print(f"    ✓ Existing Orders: {orders}")
    except Exception as e:
        print(f"    ℹ Upstream OMS Note: {e}")

    print("\n==========================================================")
    print("      Demo Completed: Native SDK Drop-in Successful!      ")
    print("==========================================================")

if __name__ == "__main__":
    main()
