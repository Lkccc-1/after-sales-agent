"""用官方 MCP 客户端走 stdio 调 server，验证工具可被外部进程发现和调用。

产出 assets/mcp-smoke.txt 作为命令行证据；Inspector 截图另存。
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE = Path(__file__).resolve().parent.parent
SERVER = BASE / "mcp_server" / "server.py"
OUT = BASE / "assets" / "mcp-smoke.txt"


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    lines: list[str] = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            lines.append("tools: " + ", ".join(t.name for t in tools.tools))
            for name, args in [
                ("order_lookup", {"order_id": "A20241105001"}),
                ("order_lookup", {"order_id": "A99999999"}),
                ("policy_search", {"query": "七天无理由退货有什么条件？", "top_k": 2}),
            ]:
                res = await session.call_tool(name, args)
                text = "\n".join(getattr(c, "text", str(c)) for c in res.content)
                is_err = getattr(res, "isError", getattr(res, "is_error", None))
                lines.append(f"\n[{name}] {args}\nisError={is_err}\n{text}")
    report = "\n".join(lines)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
