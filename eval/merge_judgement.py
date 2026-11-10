# -*- coding: utf-8 -*-
"""把判分代理返回的 JSON 合并进 结果_{version}.csv，并打印统计。

用法：
    python -I merge_judgement.py --version v1 --judgement judgement_v1.json
    python -I merge_judgement.py --version v2 --judgement judgement_v2.json

judgement JSON 格式：
    [{"id":"E01","pass":true,"failure_type":"","reason":"...","tool":"知识检索"}, ...]

合并会就地覆盖 结果_{version}.csv 的 实际分类/工具调用/是否正确/失败类型/归因说明 五列，
其它列保持原样。统计结果同时写入 汇总_{version}.json。
"""
import argparse
import csv
import json
import os
from collections import Counter, OrderedDict

FIELDS = [
    "编号", "版本", "输入", "上一轮输入", "实际输出", "实际分类", "工具调用",
    "是否正确", "失败类型", "归因说明", "测试时间", "会话ID", "工作流运行ID",
    "响应耗时秒", "检索片段数", "token用量",
]
FAIL_TYPES = ["检索错", "工具错", "Prompt 错", "模型能力不足", "知识缺失"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, choices=["v1", "v2"])
    ap.add_argument("--judgement", required=True)
    ap.add_argument("--dir", default=".")
    ap.add_argument("--cases", default="评测集.csv")
    args = ap.parse_args()

    with open(args.judgement, encoding="utf-8") as f:
        judged = {x["id"]: x for x in json.load(f)}
    with open(os.path.join(args.dir, "结果_%s.csv" % args.version), encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with open(args.cases, encoding="utf-8-sig", newline="") as f:
        cases = {r["编号"]: r for r in csv.DictReader(f)}

    missing = [r["编号"] for r in rows if r["编号"] not in judged]
    if missing:
        raise SystemExit("判分缺失：%s" % missing)

    for r in rows:
        j = judged[r["编号"]]
        r["工具调用"] = j.get("tool", "")
        r["是否正确"] = "是" if j.get("pass") else "否"
        r["失败类型"] = j.get("failure_type", "") or ""
        r["归因说明"] = j.get("reason", "") or ""
        if not r.get("实际分类"):
            r["实际分类"] = "—"

    with open(os.path.join(args.dir, "结果_%s.csv" % args.version), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    total = len(rows)
    passed = sum(1 for r in rows if r["是否正确"] == "是")
    by_scene = OrderedDict()
    for r in rows:
        scene = cases[r["编号"]]["场景"]
        d = by_scene.setdefault(scene, [0, 0])
        d[1] += 1
        if r["是否正确"] == "是":
            d[0] += 1
    fails = [r for r in rows if r["是否正确"] == "否"]
    fail_types = Counter(r["失败类型"] or "未填" for r in fails)

    def subset(flag):
        ids = [k for k, v in cases.items() if v[flag] == "是"]
        ok = sum(1 for r in rows if r["编号"] in ids and r["是否正确"] == "是")
        return ok, len(ids)

    summary = {
        "version": args.version,
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3),
        "by_scene": {k: {"pass": v[0], "total": v[1]} for k, v in by_scene.items()},
        "multi_turn": subset("多轮"),
        "handoff": subset("应转人工"),
        "refuse": subset("应拒答"),
        "failure_types": dict(fail_types),
        "failed_ids": [r["编号"] for r in fails],
        "avg_elapsed": round(sum(float(r["响应耗时秒"]) for r in rows) / total, 1),
        "avg_refs": round(sum(float(r["检索片段数"] or 0) for r in rows) / total, 1),
    }
    with open(os.path.join(args.dir, "汇总_%s.json" % args.version), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("%s 通过 %d/%d (%.0f%%)  平均耗时 %.1fs" % (args.version, passed, total, 100.0 * passed / total, summary["avg_elapsed"]))
    for k, v in summary["by_scene"].items():
        print("  %-8s %d/%d" % (k, v["pass"], v["total"]))
    print("  多轮 %d/%d  应转人工 %d/%d  应拒答 %d/%d" % (
        summary["multi_turn"][0], summary["multi_turn"][1],
        summary["handoff"][0], summary["handoff"][1],
        summary["refuse"][0], summary["refuse"][1]))
    print("  失败类型", dict(fail_types))


if __name__ == "__main__":
    main()
