"""跑 tools/testset.csv 的 10 条题，自动判定工具选择与订单号参数。

判定口径：
- expected = none             → 不应调用任何工具
- expected = get_order        → 调用了 get_order
- expected = search_policy    → 调用了 search_policy
- expected = get_order+search_policy → 两个都调用了
参数正确：get_order 的 order_id 与题面订单号一致；search_policy 的 query 非空。
"""

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from tools.agent import run

BASE = Path(__file__).resolve().parent.parent
TESTSET = BASE / "tools" / "testset.csv"
OUT = BASE / "tools" / "result.json"
TRACE = BASE / "tools" / "trace.jsonl"


def expected_ok(expected: str, called: set[str]) -> bool:
    if expected == "none":
        return not called
    parts = set(expected.split("+"))
    return parts.issubset(called)


def args_ok(question: str, calls: list[dict]) -> bool:
    order_ids = set(re.findall(r"A\d{11}", question.upper()))
    ok = True
    for c in calls:
        if c["tool"] == "get_order":
            got = str(c["args"].get("order_id", "")).upper()
            if order_ids and got not in order_ids:
                ok = False
            if not got:
                ok = False
        if c["tool"] == "search_policy" and not c["args"].get("query"):
            ok = False
    return ok


def main() -> None:
    rows = list(csv.DictReader(open(TESTSET, encoding="utf-8-sig")))
    results = []
    with open(TRACE, "a", encoding="utf-8") as tf:
        for row in rows:
            q = row["question"]
            try:
                answer, trace = run(q)
                error = None
            except Exception as e:
                answer, trace, error = "", [], str(e)
            called = {t["tool"] for t in trace}
            res = {
                "id": row["id"],
                "question": q,
                "expected_tool": row["expected_tool"],
                "calls": [{"tool": t["tool"], "args": t["args"]} for t in trace],
                "called": sorted(called),
                "tool_ok": expected_ok(row["expected_tool"], called),
                "args_ok": args_ok(q, trace),
                "answer": answer,
                "error": error,
                "time": datetime.now().isoformat(timespec="seconds"),
            }
            results.append(res)
            tf.write(json.dumps(res, ensure_ascii=False) + "\n")
            print(
                f"{row['id']} expected={row['expected_tool']:26s} "
                f"called={','.join(sorted(called)) or 'none':30s} "
                f"tool_ok={res['tool_ok']} args_ok={res['args_ok']}"
                + (f" ERROR={error}" if error else "")
            )

    ok = sum(r["tool_ok"] for r in results)
    arg_ok = sum(r["args_ok"] for r in results)
    summary = {
        "n": len(results),
        "tool_correct": ok,
        "args_correct": arg_ok,
        "failures": [r["id"] for r in results if not (r["tool_ok"] and r["args_ok"])],
    }
    OUT.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
