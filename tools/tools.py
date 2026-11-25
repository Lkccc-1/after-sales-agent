"""两个工具的实现：订单事实查询 + 政策 BM25 检索。

设计原则：日期差、7 日窗口、过保判断这类计算放在代码里做，
模型只负责选工具和解释，不让它自己算日期。
"""

import csv  # 读订单 CSV：csv.DictReader 把每行变成 {"列名": 值} 的字典
import os  # 本文件未使用（模板残留，可删）；保留不影响运行
from datetime import date, datetime  # datetime.strptime 解析字符串日期；date.today() 取今天
from pathlib import Path  # 跨平台路径：用 / 拼路径，不手写反斜杠

import jieba  # 中文分词：把句子切成词，BM25 才有词可匹配
from rank_bm25 import BM25Okapi  # BM25 打分器：给每篇文档算一个相关度分

BASE = Path(__file__).resolve().parent.parent  # __file__=tools/tools.py → 上一级 tools/ → 再上一级项目根
ORDERS_CSV = BASE / "data" / "orders_30.csv"  # 订单表：30 条合成订单
KB_DIR = BASE / "kb"  # 知识库目录：15 篇售后政策 markdown

_docs: list[str] = []  # 每篇文档全文；下标 i 与 _names[i] 一一对应（下划线前缀 = 模块内部使用）
_names: list[str] = []  # 每篇文档文件名；检索结果里给用户看
for _p in sorted(KB_DIR.glob("*.md")):  # glob 找出所有 .md；sorted 让每次启动顺序一致（结果可复现）
    _names.append(_p.name)  # 先记文件名
    _docs.append(_p.read_text(encoding="utf-8"))  # 再记全文；文件编码坏会在这里当场抛 UnicodeDecodeError
_bm25 = BM25Okapi([list(jieba.cut(d)) for d in _docs])  # 建索引：每篇先分词成词列表再拟合；整个进程只做一次


def get_order(order_id: str) -> dict:
    """按订单号返回订单事实；日期类计算在代码里做，不让模型推。"""
    oid = order_id.strip().upper()  # 归一化：去首尾空格 + 统一大写，防模型给的格式不一致
    with open(ORDERS_CSV, encoding="utf-8") as f:  # with：代码块结束自动关文件，出异常也关
        for row in csv.DictReader(f):  # 逐行读，每行变成 dict，键就是 CSV 表头
            if row["order_id"].upper() != oid:  # 比较前两边都归一化
                continue  # 不是这一单，看下一行
            ordered = datetime.strptime(row["order_date"], "%Y-%m-%d").date()  # 字符串→datetime→只要 date（不要时分秒）
            warranty = datetime.strptime(row["warranty_end"], "%Y-%m-%d").date()  # 保修截止日
            days = (date.today() - ordered).days  # 两个 date 相减得 timedelta，.days 取整数天
            return {  # 命中立刻返回，函数结束——下面那行 error 不会执行
                "order_id": row["order_id"],  # 回传 CSV 里的原始值（大写订单号）
                "product": row["product"],  # 商品名
                "category": row["category"],  # 品类（决定 7 日无理由是否适用）
                "order_date": row["order_date"],  # 下单日期（字符串）
                "days_since_order": days,  # 代码算好的天数，模型直接读，不用自己推
                "amount": float(row["amount"]),  # CSV 里都是字符串，金额转成数字
                "status": row["status"],  # 订单状态（如已发货）
                "warranty_end": row["warranty_end"],  # 保修截止日（字符串）
                "warranty_active": date.today() <= warranty,  # 今天 ≤ 截止日 = 仍在保
                "within_7_days": days <= 7,  # 含第 7 天：还在一周内
            }
    return {"error": "order_not_found", "order_id": oid}  # 循环走完都没命中，才走到这行


def search_policy(query: str, top_k: int = 3) -> list[dict]:
    """BM25 检索 15 篇政策，返回文件名 + 片段。"""
    scores = _bm25.get_scores(list(jieba.cut(query)))  # 查询也用 jieba 切（与建索引同口径）；得 15 个分，顺序同 _docs
    idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]  # 按分数排「下标」，取前 top_k 个
    return [
        {"doc": _names[i], "score": round(float(scores[i]), 3), "excerpt": _docs[i][:300]}  # 下标→文件名/分数/前 300 字；float() 把 numpy 类型转回原生 float（float64 恰好也是 float 子类、能 json.dumps；换成 float32 就会 TypeError）
        for i in idx  # 列表推导：对每个选中的下标造一个结果 dict
    ]
