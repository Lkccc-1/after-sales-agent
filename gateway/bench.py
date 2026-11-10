import asyncio
import json
import time
from pathlib import Path

import httpx

URL = "http://127.0.0.1:8000/chat"
QUERY = "七天无理由退货有什么条件？"
N, CONC = 100, 20
OUT = Path(__file__).resolve().parent / "bench_result.json"


async def one(client: httpx.AsyncClient, sem: asyncio.Semaphore):
    async with sem:
        t = time.perf_counter()
        try:
            r = await client.post(URL, json={"query": QUERY})
            return r.status_code, (time.perf_counter() - t) * 1000
        except Exception:
            return 0, (time.perf_counter() - t) * 1000


async def main():
    sem = asyncio.Semaphore(CONC)
    async with httpx.AsyncClient(timeout=120) as c:
        res = await asyncio.gather(*[one(c, sem) for _ in range(N)])
    lat = sorted(ms for code, ms in res if code == 200)
    n_ok = len(lat)
    q = lambda p: lat[min(n_ok - 1, int(n_ok * p))] if n_ok else 0
    out = {
        "total": N,
        "ok": n_ok,
        "error": N - n_ok,
        "p50_ms": round(q(0.5)),
        "p95_ms": round(q(0.95)),
        "max_ms": round(max(lat)) if lat else 0,
        "concurrency": CONC,
    }
    print(json.dumps(out, ensure_ascii=False))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
