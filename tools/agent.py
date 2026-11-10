import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from tools.tools import get_order, search_policy

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "按订单号查询订单事实：状态、下单天数、金额、是否在 7 日窗口、是否过保。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号，如 A20241105001"}
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": "在 15 篇售后政策文档中检索相关条款，返回文件名和片段。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
]

DISPATCH = {"get_order": get_order, "search_policy": search_policy}


def run(question: str, max_steps: int = 4) -> tuple[str, list[dict]]:
    messages = [
        {
            "role": "system",
            "content": "你是电商售后助手。需要订单事实时必须调用 get_order，需要政策依据时必须调用 search_policy；不要凭空回答。",
        },
        {"role": "user", "content": question},
    ]
    trace = []
    for _ in range(max_steps):
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            return msg.content or "", trace
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            fn = DISPATCH[call.function.name]
            try:
                result = fn(**args)
            except Exception as e:  # 工具报错也要回给模型
                result = {"error": str(e)}
            trace.append({"tool": call.function.name, "args": args, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
    return "（超过最大工具调用轮数）", trace


if __name__ == "__main__":
    tests = [
        "订单 A20261012001 怎么还没发货？",
        "订单 A20241105001 的耳机坏了能退吗？",
        "生鲜坏了一半能怎么赔？",
        "七天无理由退货有什么条件？",
        "推荐一款便宜的手机",
    ]
    with open(BASE / "tools" / "trace.jsonl", "a", encoding="utf-8") as f:
        for q in tests:
            answer, trace = run(q)
            f.write(
                json.dumps(
                    {
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "question": q,
                        "answer": answer,
                        "tools": trace,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            print("Q:", q)
            print("工具:", [t["tool"] for t in trace])
            print("A:", answer[:160], "\n")
