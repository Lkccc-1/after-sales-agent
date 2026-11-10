import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer

from tools.tools import get_order, search_policy

mcp = MCPServer("aftersales-tools")


@mcp.tool()
def order_lookup(order_id: str) -> dict:
    """按订单号查询订单状态、下单天数、金额、是否在 7 日窗口、是否过保。"""
    return get_order(order_id)


@mcp.tool()
def policy_search(query: str, top_k: int = 3) -> list[dict]:
    """检索 15 篇售后政策，返回文件名、相关度分数和片段。"""
    return search_policy(query, top_k)


if __name__ == "__main__":
    mcp.run()
