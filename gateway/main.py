import asyncio  # 重试之间 sleep 用：asyncio.sleep 是异步等待，不占线程
import json  # 把日志 dict 序列化成一行 JSON
import logging  # 标准库日志：同时写文件 + 终端
import os  # 读环境变量
import re  # 正则：剥思维链
import time  # 计时：perf_counter 算 latency
import uuid  # 生成 trace_id
from contextlib import asynccontextmanager  # 把「带 yield 的异步函数」变成启动/关闭上下文管理器
from pathlib import Path  # 跨平台路径

import httpx  # 异步 HTTP 客户端：网关用它调 Dify
from dotenv import load_dotenv  # 把 .env 的 KEY=VALUE 读进环境变量
from fastapi import FastAPI, HTTPException  # Web 框架；HTTPException 用来返回错误状态码
from pydantic import BaseModel, Field  # BaseModel 是校验父类；Field 给字段加规则

ROOT = Path(__file__).resolve().parent.parent  # 项目根：本文件在 gateway/ 下，parent 是 gateway，再 parent 才是根
load_dotenv(ROOT / ".env")  # 只加载不返回；默认不覆盖已存在的环境变量

DIFY_BASE = os.getenv("DIFY_BASE_URL", "http://localhost:8080")  # Dify 地址，第二个参数是默认值
DIFY_KEY = os.getenv("DIFY_API_KEY", "")  # Key 只从环境变量取，不写死；缺失时空串，请求会 401
TIMEOUT = float(os.getenv("DIFY_TIMEOUT", "60"))  # 环境变量读出来是字符串，转 float 才能给 httpx
STRIP_REASONING = os.getenv("STRIP_REASONING", "1") == "1"  # 字符串 "1" 比较后得到布尔；默认开
_REASONING_RE = re.compile(r"<think>.*?</think>", re.S | re.I)  # ?=懒惰，逐块剥；S=让 . 匹配换行，I=忽略大小写

LOG_DIR = ROOT / "logs"  # 日志目录
LOG_DIR.mkdir(exist_ok=True)  # 不存在就建；exist_ok=True 表示目录已存在也不报错
logger = logging.getLogger("gateway")  # 按名字取 logger（模块级单例）
logger.setLevel(logging.INFO)  # 记录 INFO 及以上级别
_fmt = logging.Formatter("%(message)s")  # 只输出消息本身：消息已经是 JSON，不再加时间/级别前缀
for h in (  # 同时挂两个 handler：一个写文件、一个打终端
    logging.FileHandler(LOG_DIR / "gateway.jsonl", encoding="utf-8"),  # 追加写；utf-8 防中文乱码
    logging.StreamHandler(),  # 输出到控制台
):
    h.setFormatter(_fmt)  # 两个 handler 共用同一格式
    logger.addHandler(h)  # 挂到 logger 上

client: httpx.AsyncClient | None = None  # 全局连接池；启动时在 lifespan 里创建，None 表示还没建


@asynccontextmanager  # 装饰器：把下面的异步生成器变成 lifespan 要的上下文管理器
async def lifespan(app: FastAPI):  # FastAPI 在启动时进入、关闭时退出
    global client  # 关键：函数内给模块级变量赋值必须声明；漏了 client 只是局部变量，模块级仍是 None，第一个请求 502
    client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT, connect=5.0))  # 建连接池：总超时 TIMEOUT，建立连接最多 5 秒
    yield  # 执行到这里暂停：yield 前 = 启动时跑一次，应用运行期间连接池一直活着
    await client.aclose()  # yield 后 = 关闭时跑一次：释放连接池


app = FastAPI(title="售后智服 Gateway", version="1.0", lifespan=lifespan)  # 把 lifespan 接上；装饰器只负责变形，这里才是接线


class ChatIn(BaseModel):  # 入站合同：请求体允许有哪些字段（没有 __init__，交给 BaseModel 按字段表构造）
    query: str = Field(min_length=1, max_length=2000)  # 必填；空串/超长在进函数前就被拦下，自动返回 422
    conversation_id: str | None = None  # 可选：字符串或 None；不传时默认 None
    user: str = "demo-user"  # 可选，有默认值


class ChatOut(BaseModel):  # 出站合同：响应必须长这样
    answer: str  # 清理过思维链的答案
    conversation_id: str  # Dify 的会话 ID，多轮对话要带回来
    trace_id: str  # 本次请求的追踪 ID
    latency_ms: int  # 网关侧耗时（毫秒）
    tokens: int | None = None  # 上游可能没给 usage，允许 None


def clean_answer(text: str) -> str:  # 对外答案清洗：剥掉模型思维链
    """Dify 的 deepseek-flash 会把思维链写进 answer，对外 API 不应暴露。"""  # docstring：解释为什么需要这个函数
    if not STRIP_REASONING:  # 开关关掉时（调试）原样返回
        return text
    return _REASONING_RE.sub("", text).strip()  # sub 把所有匹配替换成空串；strip 清掉首尾残留空白


async def call_dify(payload: dict) -> dict:  # 调 Dify 的唯一入口
    """3 次重试，指数退避；只重试超时和 429/5xx。"""  # 注意：注释与实现不符——下面 raise_for_status 会让 401/400 也进入重试（已知 bug）
    last_exc: Exception | None = None  # 保存最后一次异常；except ... as e 的 e 出了 except 块就被删掉
    for attempt in range(3):  # attempt = 0,1,2，一共 3 次
        try:
            r = await client.post(  # await：等网络时不占线程，事件循环去处理别的请求
                f"{DIFY_BASE}/v1/chat-messages",  # Dify 对话接口
                headers={"Authorization": f"Bearer {DIFY_KEY}"},  # Bearer 认证，Key 来自环境变量
                json=payload,  # httpx 自动把 dict 序列化并设置 Content-Type
            )
            if r.status_code in (429, 500, 502, 503, 504):  # 这些是暂时性故障，值得重试
                raise httpx.HTTPStatusError(  # 手动抛同类异常，统一走下面的 except
                    f"retryable {r.status_code}", request=r.request, response=r
                )
            r.raise_for_status()  # 其他 4xx/5xx 也抛 HTTPStatusError —— 401/400 因此也被重试，bug 根源
            return r.json()  # 2xx：解析并返回，函数立即结束
        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:  # 接住超时和 HTTP 错误
            last_exc = e  # 存下来，循环外再抛
            if attempt < 2:  # 第 3 次失败后没有第 4 次了，不该再睡
                await asyncio.sleep(0.5 * (2**attempt))  # 指数退避：第 1 次失败后 0.5 秒，第 2 次后 1 秒
    # 3 次都失败：把最后一次异常抛出去，交给路由层转 502
    raise last_exc  # type: ignore[misc]


@app.get("/healthz")  # 注册 GET 路由：浅检查，不碰 Dify，只证明网关进程活着
async def healthz():
    return {"ok": True}  # FastAPI 自动转成 JSON


@app.post("/chat", response_model=ChatOut)  # 注册 POST 路由；出站按 ChatOut 校验/裁剪，并生成 OpenAPI 文档
async def chat(body: ChatIn):  # body 由 FastAPI 从请求体构造并校验；不合格自动 422，进不到函数体
    trace_id = uuid.uuid4().hex[:12]  # 12 位十六进制追踪 ID，串起本次请求的所有日志
    t0 = time.perf_counter()  # 高精度计时起点
    payload = {  # 转成 Dify 要的请求格式
        "inputs": {},  # Dify 应用变量，这里没有
        "query": body.query,  # 用户问题
        "response_mode": "blocking",  # 阻塞模式：等完整答案再返回（另一种是 streaming）
        "conversation_id": body.conversation_id or "",  # 空串 = 新会话；客户端传回则续聊
        "user": body.user,  # 区分终端用户
    }
    try:
        data = await call_dify(payload)  # 调上游；失败会抛异常
    except Exception as e:  # 上游任何失败都在这里兜住，不让 500 裸奔
        logger.info(  # 错误也写同一份 jsonl，用 status 区分
            json.dumps(
                {
                    "trace_id": trace_id,  # 同一请求可与成功日志对上
                    "status": "error",  # 状态标记
                    "error": str(e),  # 异常文本（不含用户原文）
                    "query_len": len(body.query),  # 只记长度，不记原文（隐私）
                },
                ensure_ascii=False,  # 中文不转 \uXXXX，日志可读
            )
        )
        raise HTTPException(status_code=502, detail=f"dify error: {e}")  # 502=网关的上游故障；raise 后本函数立即结束

    latency = int((time.perf_counter() - t0) * 1000)  # 耗时转毫秒整数
    usage = (data.get("metadata") or {}).get("usage") or {}  # 逐层兜底：metadata / usage 可能缺失或为 None
    tokens = usage.get("total_tokens")  # 拿不到就是 None，不影响主流程
    logger.info(  # 成功日志：之后所有数字统计都来自这里
        json.dumps(
            {
                "trace_id": trace_id,
                "status": "ok",
                "conversation_id": data.get("conversation_id"),  # 续聊要带回去
                "query_len": len(body.query),  # 只记长度
                "latency_ms": latency,
                "tokens": tokens,
            },
            ensure_ascii=False,
        )
    )
    return ChatOut(  # 按出站合同构造；字段缺失/类型不对在这里就暴露
        answer=clean_answer(data.get("answer", "")),  # 剥思维链；上游没答案就给空串
        conversation_id=data.get("conversation_id", ""),
        trace_id=trace_id,
        latency_ms=latency,
        tokens=tokens,
    )
