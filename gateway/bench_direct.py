"""直连 Dify 与经网关的端到端延迟对照。

交替发同一问题各 N 次，比较中位数。模型耗时波动远大于网关开销，
所以结论只能说明「网关开销在噪声范围内」，不能精确到毫秒。
"""

import json
import os
import statistics
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DIFY = os.getenv("DIFY_BASE_URL", "http://localhost:8080")
KEY = os.getenv("DIFY_API_KEY", "")
QUERY = "七天无理由退货有什么条件？"
N = 6
OUT = Path(__file__).resolve().parent / "direct_result.json"


def timed_direct(client: httpx.Client) -> float:
    t = time.perf_counter()
    r = client.post(
        f"{DIFY}/v1/chat-messages",
        headers={"Authorization": f"Bearer {KEY}"},
        json={
            "inputs": {},
            "query": QUERY,
            "response_mode": "blocking",
            "conversation_id": "",
            "user": "bench-direct",
        },
    )
    r.raise_for_status()
    return (time.perf_counter() - t) * 1000


def timed_gateway(client: httpx.Client) -> float:
    t = time.perf_counter()
    r = client.post("http://127.0.0.1:8000/chat", json={"query": QUERY})
    r.raise_for_status()
    return (time.perf_counter() - t) * 1000


def main() -> None:
    direct, gateway = [], []
    with httpx.Client(timeout=120) as c:
        for i in range(N):
            direct.append(timed_direct(c))
            gateway.append(timed_gateway(c))
            print(f"round {i + 1}: direct={direct[-1]:.0f}ms gateway={gateway[-1]:.0f}ms")

    out = {
        "n": N,
        "direct_ms": [round(x) for x in direct],
        "gateway_ms": [round(x) for x in gateway],
        "direct_median_ms": round(statistics.median(direct)),
        "gateway_median_ms": round(statistics.median(gateway)),
        "median_diff_ms": round(statistics.median(gateway) - statistics.median(direct)),
    }
    print(json.dumps(out, ensure_ascii=False))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
