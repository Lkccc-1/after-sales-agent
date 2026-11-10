import asyncio
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DIFY_BASE = os.getenv("DIFY_BASE_URL", "http://localhost:8080")
DIFY_KEY = os.getenv("DIFY_API_KEY", "")
TIMEOUT = float(os.getenv("DIFY_TIMEOUT", "60"))
STRIP_REASONING = os.getenv("STRIP_REASONING", "1") == "1"
_REASONING_RE = re.compile(r"<think>.*?</think>", re.S | re.I)

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
logger = logging.getLogger("gateway")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(message)s")
for h in (
    logging.FileHandler(LOG_DIR / "gateway.jsonl", encoding="utf-8"),
    logging.StreamHandler(),
):
    h.setFormatter(_fmt)
    logger.addHandler(h)

client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT, connect=5.0))
    yield
    await client.aclose()


app = FastAPI(title="售后智服 Gateway", version="1.0", lifespan=lifespan)


class ChatIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    user: str = "demo-user"


class ChatOut(BaseModel):
    answer: str
    conversation_id: str
    trace_id: str
    latency_ms: int
    tokens: int | None = None


def clean_answer(text: str) -> str:
    """Dify 的 deepseek-flash 会把思维链写进 answer，对外 API 不应暴露。"""
    if not STRIP_REASONING:
        return text
    return _REASONING_RE.sub("", text).strip()


async def call_dify(payload: dict) -> dict:
    """3 次重试，指数退避；只重试超时和 429/5xx。"""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            r = await client.post(
                f"{DIFY_BASE}/v1/chat-messages",
                headers={"Authorization": f"Bearer {DIFY_KEY}"},
                json=payload,
            )
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(
                    f"retryable {r.status_code}", request=r.request, response=r
                )
            r.raise_for_status()
            return r.json()
        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
            last_exc = e
            if attempt < 2:
                await asyncio.sleep(0.5 * (2**attempt))
    raise last_exc  # type: ignore[misc]


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn):
    trace_id = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    payload = {
        "inputs": {},
        "query": body.query,
        "response_mode": "blocking",
        "conversation_id": body.conversation_id or "",
        "user": body.user,
    }
    try:
        data = await call_dify(payload)
    except Exception as e:
        logger.info(
            json.dumps(
                {
                    "trace_id": trace_id,
                    "status": "error",
                    "error": str(e),
                    "query_len": len(body.query),
                },
                ensure_ascii=False,
            )
        )
        raise HTTPException(status_code=502, detail=f"dify error: {e}")

    latency = int((time.perf_counter() - t0) * 1000)
    usage = (data.get("metadata") or {}).get("usage") or {}
    tokens = usage.get("total_tokens")
    logger.info(
        json.dumps(
            {
                "trace_id": trace_id,
                "status": "ok",
                "conversation_id": data.get("conversation_id"),
                "query_len": len(body.query),
                "latency_ms": latency,
                "tokens": tokens,
            },
            ensure_ascii=False,
        )
    )
    return ChatOut(
        answer=clean_answer(data.get("answer", "")),
        conversation_id=data.get("conversation_id", ""),
        trace_id=trace_id,
        latency_ms=latency,
        tokens=tokens,
    )
