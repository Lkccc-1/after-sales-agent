# 售后智服 · 电商售后智能体（工程补强版）

> 这是「售后智服」作品集的工程仓库：Dify Chatflow 之上的 FastAPI 网关、Function Calling 工具集、
> RAG 对比实验与 MCP Server。产品侧材料见[作品集站点](https://lkccc-1.github.io/after-sales-agent-dify/)。

## 它解决什么问题

电商售后咨询里，订单事实（发货没、几天了、过保没）和政策依据（能不能退、扣多少）分散在
订单系统和 15 篇政策文档里。这个项目把它们做成一个可被业务系统调用的智能体：
模型决定调哪个工具、工具返回事实、模型组织回答，全过程留结构化日志。

## 架构

```
业务系统 / 前端
      │
      ▼
FastAPI 网关 (gateway/)  ← 超时重试、trace_id 日志、并发入口
      │
      ▼
Dify Chatflow (dify/ 里的 DSL)  ← 意图分流、政策问答、多轮
      │
      ├─ tools/get_order       订单事实（本地 CSV，模拟订单系统）
      └─ tools/search_policy   政策检索（BM25 over kb/）
```

## Demo

- 4 分钟演示：作品集站内 `assets/demo-4min.mp4`
- 评测：Dify 工作流 28/30（小样本，口径见 `eval/` 与 `docs/06-eval-report.md`）

## 怎么跑

```bash
cp .env.example .env        # 填入 Dify API Key（app- 开头）
python -m venv .venv
source .venv/Scripts/activate   # Git Bash
pip install -r requirements.txt

uvicorn gateway.main:app --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/chat -H "Content-Type: application/json" \
  -d '{"query":"七天无理由退货有什么条件？"}'
```

## 目录

| 目录 | 内容 |
|---|---|
| `gateway/` | FastAPI 网关、压测脚本与结果 |
| `tools/` | Function Calling 工具实现与调用链 |
| `rag/` | LlamaIndex 检索对比实验 |
| `mcp_server/` | MCP 工具服务 |
| `eval/` | 评测集与评测脚本（来自作品集 06_评测） |
| `dify/` | Dify 工作流 DSL（可导入复现） |
| `data/`、`kb/` | 模拟订单与 15 篇政策文档 |
| `docs/` | 场景、旅程、边界、方案等产品文档 |

## 局限（如实写）

- 订单是模拟数据，没有接真实订单系统。
- 没有身份核验，任何人知道订单号就能查。
- Dify 本机单机部署，压测结论只在 20 并发口径内成立。
- 评测是小样本（30 条），不代表线上分布。

## 证据

| 证据 | 文件 | 证明什么 |
|---|---|---|
| 网关日志 | `logs/gateway_sample.jsonl` | 每行含 `trace_id`、`latency_ms`、`tokens`，可逐行解析 |
| 压测结果 | `gateway/bench_result.json`、`gateway/bench.md` | 100 次 / 20 并发：p50 14.1s、p95 18.2s、错误率 0% |
| 直连对照 | `gateway/direct_result.json` | 网关开销无法与模型波动分离（如实记录，不编数字） |
| 工具调用链 | `tools/trace.jsonl` | 11 条问题、13 次工具调用，含参数与结果 |
| 工具评测 | `tools/report.md`、`tools/result.json` | 预标注 9/11，复核后 11/11 合理；参数 11/11 |
| RAG 对比 | `rag/result.json`、`rag/report.md` | 3 分段 × 2 TopK 的 doc/top1/MRR/clause 四项指标 |
| MCP 命令行验证 | `assets/mcp-smoke.txt` | 外部 MCP 客户端能列出并调用两个工具 |
| MCP Inspector | `assets/mcp-inspector.png` | 可视化列出 2 个工具并调用 `order_lookup` 成功返回订单字段 |
| 工作流 DSL | `dify/售后智服-v2.yaml` | 可导入复现 |

## 已知问题

- **`<think>` 推理标签（已修复，2026-11-10）**：`deepseek-flash` 会把思维链写进 `answer`。网关层用 `clean_answer` 剥离；网页端在工作流 3 个 LLM 节点后各加一个「剥离思维链」代码节点，`dify/售后智服-v2.yaml` 已同步。剥离只删标签，不改回答内容，评测口径不变。
- 订单是模拟数据；无身份核验；单机部署结论只在 20 并发口径内成立。
