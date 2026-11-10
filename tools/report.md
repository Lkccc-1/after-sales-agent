# Function Calling 工具评测

- 日期：2026-11-10
- 模型：`deepseek-chat`（DeepSeek 官方 API），`temperature=0.2`，`max_steps=4`
- 题目：`tools/testset.csv`，11 条单轮问题（从 30 条评测集里挑，覆盖政策/订单/混合/超范围）
- 原始记录：`tools/result.json`、`tools/trace.jsonl`（11 条记录，共 13 次工具调用）
- 判定口径：`none` 不调工具；`get_order` / `search_policy` 至少调到；`+` 表示两个都要调

## 结果

| # | 问题 | 期望工具 | 实际调用 | 工具选择 | 参数 | 答案可用 |
|---|---|---|---|---|---|---|
| E01 | 七天无理由退货有什么条件？ | search_policy | search_policy | ✅ | ✅ | ✅ |
| E02 | 退款多久能到账？ | search_policy | search_policy | ✅ | ✅ | ✅ |
| E04 | 退货时原包装坏了会扣多少钱？ | search_policy | search_policy | ✅ | ✅ | ✅ |
| E06 | 换货有什么条件？运费谁出？ | search_policy | search_policy | ✅ | ✅ | ✅ |
| E07 | 过保了还能免费维修吗？ | search_policy | search_policy | ✅ | ✅ | ✅ |
| E09 | 订单 A20241105001 到哪了？ | get_order+search_policy | get_order | ⚠️ 标注过严 | ✅ | ✅ |
| E10 | 订单 A20260918002 什么时候发货？ | get_order+search_policy | get_order | ⚠️ 标注过严 | ✅ | ✅ |
| E11 | 订单 A20261012001 怎么还没发货？ | get_order+search_policy | get_order → search_policy | ✅ | ✅ | ✅ |
| E12 | 订单 A20260925001 我想申请退款 | get_order | get_order → search_policy | ✅（多调 1 次） | ✅ | ✅ |
| E15 | 订单 A20241105001 的耳机坏了能退吗？ | get_order+search_policy | get_order → search_policy | ✅ | ✅ | ✅ |
| E30 | 推荐一款便宜的手机 | none | 无调用 | ✅ | ✅ | ✅ |

**汇总**

- 按**预先标注**的口径：工具选择 9/11，参数抽取 11/11。
- 逐条复核答案后：**11/11 的工具选择都合理**，参数 11/11，最终答案 11/11 可用（人工判断）。
- 没有出现「该调工具却没调」或「订单号抽错」；唯一的真偏差是 E12 多调了一次检索。

## 偏差分析（比数字更值钱）

1. **E09 / E10 是标注错，不是模型错。** 这两题问的是「到哪了」「什么时候发货」，订单状态（已签收 / 运输中）已经能回答，不需要政策检索。我一开始把「带订单号的问题」一律标成双工具，是按模板偷懒。复核结论：模型只调 `get_order` 是对的，**标注必须按问题意图校准，否则会制造假失败**。
2. **E12 多调了一次 `search_policy`。** 题面只要订单事实，模型额外查了退款政策。答案因此更能解释「已取消订单的退款」——不算错，但多一次检索 = 多一次延迟和 token。若追求成本，可在系统提示里收紧「只查与问题直接相关的内容」。
3. **E30 正确不调工具**，直接说明自己是售后助手、不做商品推荐——这条验证了工具的「不该调时不调」。

## 调用链证据

`tools/trace.jsonl` 每条记录都含 `calls`（工具名 + 参数）与最终 `answer`，例如 E11 的链路：

```
问题 → get_order(A20261012001) → 工具结果(待发货/29 天)
     → search_policy("订单未发货 延迟发货 处理规则 赔付") → 工具结果(48 小时/15 日)
     → 模型组织答案(指出已超时 + 可选处理)
```

13 次工具调用中 3 道题发生了「模型 → 工具 → 模型 → 工具 → 模型」的多轮链路，说明不是一次性的伪调用。

## 复现

```bash
python -m tools.run_tests      # 跑 11 条评测，写 result.json 与 trace.jsonl
python -m tools.agent          # 跑内置的 5 条冒烟题
```
