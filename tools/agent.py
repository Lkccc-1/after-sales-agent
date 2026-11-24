import json #解析模型返回的 arguments 字符串；写 JSONL 日志也用
import os#读环境变量（os.getenv 取 DEEPSEEK_API_KEY）
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from tools.tools import get_order, search_policy#包和模块定义两个函数

BASE = Path(__file__).resolve().parent.parent#基于当前文件项目根
load_dotenv(BASE / ".env")#把.env里面的KEY=VALUE读进环境变量，只加载不返回配置
client = OpenAI(#写在模块级：整个进程只建一次，所有run（）共用
    api_key=os.getenv("DEEPSEEK_API_KEY"),#api_key从环境变量取，不写死在代码里
    base_url="https://api.deepseek.com",#连接上deepseek的url
)

TOOLS = [#给模型看的产品说明书
    {
        "type": "function",#OpenAI协议规定固定值
        "function": {
            "name": "get_order",#模型用这个字符串点菜
            "description": "按订单号查询订单事实：状态、下单天数、金额、是否在 7 日窗口、是否过保。",#写给模型看的，模型靠它判断什么时候该用这个工具
            "parameters": {#json schema
                "type": "object",#表示参数是一个对象
                "properties": {#列每个参数类型
                    "order_id": {"type": "string", "description": "订单号，如 A20241105001"}
                },
                "required": ["order_id"],#代表必填项
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

DISPATCH = {"get_order": get_order, "search_policy": search_policy}#把字符串变成真正的函数对象


def run(question: str, max_steps: int = 4) -> tuple[str, list[dict]]:#返回最终答案和调用记录
    messages = [#对话历史。API 无状态，服务器不记得上一轮，所以每次请求都要整段重发
        {
            "role": "system",
            "content": "你是电商售后助手。需要订单事实时必须调用 get_order，需要政策依据时必须调用 search_policy；不要凭空回答。",
        },
        {"role": "user", "content": question},
    ]
    trace = []#给日志和调试用的，不是给用户看的
    for _ in range(max_steps):#最多4轮，防止死循环
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,#把上面TOOLS的菜单交给模型
            tool_choice="auto",#让模型自己决定直接答还是调用工具
            temperature=0.2,#售后场景要稳定，不要发挥
        )
        msg = resp.choices[0].message#只取第一个候选
        messages.append(msg.model_dump(exclude_none=True))#助手消息必须入历史：下一轮 tool 消息要靠 tool_calls 里的 id配对；exclude_none 去掉 SDK 带出的 None 字段
        if not msg.tool_calls:
            return msg.content or "", trace#模型没点菜，可以直接回答
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")#json字符串必须用json.loads，后面or模型可能给空串/None，兜成空对象，避免 json.loads("") 报错
            fn = DISPATCH[call.function.name]#字符串变成函数对象
            try:
                result = fn(**args)#把dict拆成关键字参数
            except Exception as e:  # 工具报错也要回给模型
                result = {"error": str(e)}
            trace.append({"tool": call.function.name, "args": args, "result": result})#trace记下调用什么工具，传了什么，返回了什么
            messages.append(
                {
                    "role": "tool",#协议规定的角色
                    "tool_call_id": call.id,#必须等于刚才那次调用的call.id，配对身份证
                    "content": json.dumps(result, ensure_ascii=False),#中文原样保留
                }
            )
    return "（超过最大工具调用轮数）", trace#4 轮还没答完：宁可说没搞定，也不无限循环


if __name__ == "__main__":#只有直接运行这个文件才执行，被import时不执行，测试代码不污染别人
    tests = [
        "订单 A20261012001 怎么还没发货？",
        "订单 A20241105001 的耳机坏了能退吗？",
        "生鲜坏了一半能怎么赔？",
        "七天无理由退货有什么条件？",
        "推荐一款便宜的手机",
    ]
    with open(BASE / "tools" / "trace.jsonl", "a", encoding="utf-8") as f:#with表示离开代码块自动关文件，异常也会关，a表示追加不覆盖历史，encoding不写会出中文乱码
        for q in tests:
            answer, trace = run(q)
            f.write(
                json.dumps(
                    {
                        "time": datetime.now().isoformat(timespec="seconds"),#时间戳精确到秒，给日志排序用
                        "question": q,
                        "answer": answer,
                        "tools": trace,# 本轮所有工具调用记录（来自上面的 trace）
                    },
                    ensure_ascii=False,#中文原样写，不转成 \u8ba2\u5355
                )
                + "\n"#每行一个 JSON（JSONL），没有它整个文件就是一行
            )
            print("Q:", q)
            print("工具:", [t["tool"] for t in trace])#列表推导：从 trace 里只抽出工具名
            print("A:", answer[:160], "\n")#切片截断，终端只打印前160个字符
