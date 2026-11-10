"""两个工具的实现：订单事实查询 + 政策 BM25 检索。

设计原则：日期差、7 日窗口、过保判断这类计算放在代码里做，
模型只负责选工具和解释，不让它自己算日期。
"""

import csv
import os
from datetime import date, datetime
from pathlib import Path

import jieba
from rank_bm25 import BM25Okapi

BASE = Path(__file__).resolve().parent.parent
ORDERS_CSV = BASE / "data" / "orders_30.csv"
KB_DIR = BASE / "kb"

_docs: list[str] = []
_names: list[str] = []
for _p in sorted(KB_DIR.glob("*.md")):
    _names.append(_p.name)
    _docs.append(_p.read_text(encoding="utf-8"))
_bm25 = BM25Okapi([list(jieba.cut(d)) for d in _docs])


def get_order(order_id: str) -> dict:
    """按订单号返回订单事实；日期类计算在代码里做，不让模型推。"""
    oid = order_id.strip().upper()
    with open(ORDERS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["order_id"].upper() != oid:
                continue
            ordered = datetime.strptime(row["order_date"], "%Y-%m-%d").date()
            warranty = datetime.strptime(row["warranty_end"], "%Y-%m-%d").date()
            days = (date.today() - ordered).days
            return {
                "order_id": row["order_id"],
                "product": row["product"],
                "category": row["category"],
                "order_date": row["order_date"],
                "days_since_order": days,
                "amount": float(row["amount"]),
                "status": row["status"],
                "warranty_end": row["warranty_end"],
                "warranty_active": date.today() <= warranty,
                "within_7_days": days <= 7,
            }
    return {"error": "order_not_found", "order_id": oid}


def search_policy(query: str, top_k: int = 3) -> list[dict]:
    """BM25 检索 15 篇政策，返回文件名 + 片段。"""
    scores = _bm25.get_scores(list(jieba.cut(query)))
    idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [
        {"doc": _names[i], "score": round(float(scores[i]), 3), "excerpt": _docs[i][:300]}
        for i in idx
    ]
