# -*- coding: utf-8 -*-
"""Day 8 评测脚本：把 评测集.csv 批量跑一遍，v1 / v2 分开跑。

用法（在 06_评测 目录下）：
    set DIFY_V1_KEY=app-xxxxxxxx
    python -I run_eval.py --version v1
    set DIFY_V2_KEY=app-xxxxxxxx
    python -I run_eval.py --version v2

说明：
- 每条用例单独开新会话；多轮用例在同一会话里先发「上一轮输入」再发「输入」。
- 原始响应存 原始结果_{version}.json，可回查引用片段和 token。
- 结果表 结果_{version}.csv 的人审列留空，跑完手工填 是否正确/失败类型/归因。
- API Key 只从环境变量读，不写盘、不打印。
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("DIFY_BASE", "http://localhost:8080").rstrip("/")
KEYS = {"v1": os.environ.get("DIFY_V1_KEY", ""), "v2": os.environ.get("DIFY_V2_KEY", "")}
TIMEOUT = 180
RESULT_FIELDS = [
    "编号", "版本", "输入", "上一轮输入", "实际输出", "实际分类", "工具调用",
    "是否正确", "失败类型", "归因说明", "测试时间", "会话ID", "工作流运行ID",
    "响应耗时秒", "检索片段数", "token用量",
]


def post_chat(key, query, conversation_id="", user="eval"):
    body = {
        "inputs": {},
        "query": query,
        "response_mode": "blocking",
        "conversation_id": conversation_id,
        "user": user,
        "auto_generate_name": False,
    }
    req = urllib.request.Request(
        BASE + "/v1/chat-messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_with_retry(key, query, conversation_id="", user="eval"):
    last_err = None
    for attempt in range(2):
        try:
            return post_chat(key, query, conversation_id, user)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            last_err = "HTTP %s: %s" % (e.code, detail)
            if e.code < 500:
                break
        except Exception as e:  # 超时、连接失败
            last_err = "%s: %s" % (type(e).__name__, e)
        if attempt == 0:
            time.sleep(5)
    raise RuntimeError(last_err)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, choices=["v1", "v2"])
    ap.add_argument("--csv", default="评测集.csv")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--sleep", type=float, default=1.5, help="两条用例间隔秒数")
    ap.add_argument("--ids", default="", help="只跑指定编号，逗号分隔，如 E01,E11")
    args = ap.parse_args()

    key = KEYS[args.version]
    if not key:
        sys.exit("缺少环境变量 DIFY_%s_KEY" % args.version.upper())

    with open(args.csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if args.ids:
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        rows = [r for r in rows if r["编号"].strip() in want]
        if not rows:
            sys.exit("--ids 没有匹配到任何用例：%s" % args.ids)

    raw_all, outline = [], []
    for i, r in enumerate(rows, 1):
        eid = r["编号"].strip()
        prev = (r.get("上一轮输入") or "").strip()
        query = r["输入"].strip()
        started = time.time()
        rec = {"id": eid, "version": args.version, "turns": []}
        status = "ok"
        try:
            if prev:
                rec["turns"].append({"query": prev, "response": post_with_retry(key, prev, user="eval-" + args.version)})
                cid = rec["turns"][-1]["response"].get("conversation_id", "")
                time.sleep(1)
            else:
                cid = ""
            final = post_with_retry(key, query, cid, user="eval-" + args.version)
            rec["turns"].append({"query": query, "response": final})
        except Exception as e:
            status = "error"
            final = {"answer": "[请求失败] " + str(e)}
            rec["error"] = str(e)

        elapsed = round(time.time() - started, 1)
        meta = final.get("metadata") or {}
        refs = meta.get("retriever_resources") or []
        usage = meta.get("usage") or {}
        tokens = usage.get("total_tokens") or usage.get("total_usage") or ""
        answer = final.get("answer") or ""
        rec["elapsed"] = elapsed
        rec["status"] = status
        raw_all.append(rec)

        outline.append({
            "编号": eid,
            "版本": args.version,
            "输入": query,
            "上一轮输入": prev,
            "实际输出": answer,
            "实际分类": "",
            "工具调用": "",
            "是否正确": "",
            "失败类型": "",
            "归因说明": "",
            "测试时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "会话ID": final.get("conversation_id", ""),
            "工作流运行ID": final.get("workflow_run_id", ""),
            "响应耗时秒": elapsed,
            "检索片段数": len(refs),
            "token用量": tokens,
        })
        print("[%02d/%02d] %s %s %ss %s" % (i, len(rows), eid, status, elapsed, answer.replace("\n", " ")[:40]))

        if i < len(rows):
            time.sleep(args.sleep)

    os.makedirs(args.out_dir, exist_ok=True)
    raw_path = os.path.join(args.out_dir, "原始结果_%s.json" % args.version)
    csv_path = os.path.join(args.out_dir, "结果_%s.csv" % args.version)
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_all, f, ensure_ascii=False, indent=2)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        w.writeheader()
        w.writerows(outline)
    ok = sum(1 for x in raw_all if x["status"] == "ok")
    print("\n完成 %d/%d，输出 %s 和 %s" % (ok, len(rows), csv_path, raw_path))


if __name__ == "__main__":
    main()
