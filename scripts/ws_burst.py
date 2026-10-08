"""Fast parallel WS burst against the relay batch socket.

Opens N raw asyncio connections with slight stagger, sends one SDK-shaped
index subscribe each, holds, counts handshakes/ticks/closes. ~30s total.
"""
import asyncio
import json
import sys
import time

URI = "wss://nubra-relay-1.tail2b15c4.ts.net/apibatch/ws"
SUB = 'batch_subscribe X index {"instruments":[],"indexes":["NIFTY"]} NSE'


async def one(i, hold, out):
    import websockets

    rec = {"connected": False, "ticks": 0, "closed": "", "err": ""}
    t0 = time.time()
    try:
        async with websockets.connect(URI, max_size=10 * 1024 * 1024) as ws:
            rec["connected"] = True
            await ws.send(SUB)
            try:
                async with asyncio.timeout(hold):
                    async for msg in ws:
                        rec["ticks"] += 1
            except (asyncio.TimeoutError, TimeoutError):
                pass
    except Exception as e:
        rec["err"] = f"{type(e).__name__}: {str(e)[:100]}"
    rec["secs"] = round(time.time() - t0, 1)
    out[i] = rec


async def main(n, hold):
    out = [None] * n
    tasks = []
    for i in range(n):
        tasks.append(asyncio.create_task(one(i, hold, out)))
        await asyncio.sleep(0.05)
    await asyncio.gather(*tasks)
    conn = sum(1 for r in out if r["connected"])
    errs = {}
    for r in out:
        if r["err"]:
            errs[r["err"]] = errs.get(r["err"], 0) + 1
    ticks = sum(r["ticks"] for r in out)
    with_ticks = sum(1 for r in out if r["ticks"] > 0)
    print(
        f"BURST N={n} connected={conn}/{n} with_ticks={with_ticks}/{n} "
        f"total_ticks={ticks} error_kinds={json.dumps(errs)[:300]}",
        flush=True,
    )


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    hold = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    asyncio.run(main(n, hold))
