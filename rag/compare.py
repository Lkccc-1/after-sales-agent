"""LlamaIndex 纯向量检索：3 种分段 × 2 种 TopK 的召回对比。

指标（逐题计算）：
- doc_recall：期望文档是否出现在 top-k（文档级）
- top1_doc：第 1 条召回是否来自期望文档
- mrr：期望文档第一次出现的排名倒数
- clause_recall：top-k 中是否存在「来自期望文档且包含答案关键句」的片段

注意口径：这里是纯向量（bge-small-zh），Dify 内置是混合检索（语义 + 关键词），
两者不能直接说谁更好，报告里必须写清楚。
"""  # docstring 内部是字符串，不能插注释；这行起才是代码

import csv  # 读 labels.csv（CSV → dict 列表）
import json  # 写 result.json / 控制台打印汇总
import os  # 环境变量 + os.path.basename
from pathlib import Path  # 路径对象：拼路径、取父目录

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # 必须在 import huggingface 之前：下载地址在导入/初始化时就定了

from llama_index.core import SimpleDirectoryReader, Settings, VectorStoreIndex  # 目录读取 / 全局配置 / 向量索引
from llama_index.core.node_parser import SentenceSplitter  # 按句子切块
from llama_index.embeddings.huggingface import HuggingFaceEmbedding  # 本地 embedding 模型

BASE = Path(__file__).resolve().parent.parent  # 项目根：本文件在 rag/ 下，向上两级
LABELS = BASE / "rag" / "labels.csv"  # 题目集：12 条（期望文档 + 答案关键句）
OUT = BASE / "rag" / "result.json"  # 输出：6 组指标 + 逐题明细

Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-zh-v1.5")  # 全局 embedding：中文小模型，本地 CPU 可跑
Settings.llm = None  # 只做检索、不生成；不设的话 LlamaIndex 可能默认去连 OpenAI

docs = SimpleDirectoryReader(str(BASE / "kb")).load_data()  # 读 kb/ 下 15 篇 md → Document 列表
labels = list(csv.DictReader(open(LABELS, encoding="utf-8-sig")))  # utf-8-sig 去 BOM，否则列名会带 "﻿"


def doc_name(node) -> str:  # 片段 → 文件名，用来和 expected_doc 比对
    return os.path.basename(node.metadata.get("file_name", ""))  # get 兜底空串，缺字段也不崩


rows = []  # 6 组结果的总表
for chunk in (300, 500, 800):  # 变量 1：分段大小（字）
    index = VectorStoreIndex.from_documents(  # 建索引 = 切块 + 向量化；chunk 变了必须重建
        docs,  # 同一批文档
        transformations=[SentenceSplitter(chunk_size=chunk, chunk_overlap=chunk // 10)],  # overlap 取 10%
    )
    for k in (3, 5):  # 变量 2：TopK
        retriever = index.as_retriever(similarity_top_k=k)  # 检索器：取最相似的 k 个片段
        hit = top1 = clause_hit = 0  # 三个计数器：文档级 / Top1 / 片段级
        mrr = 0.0  # MRR 累加器（浮点）
        details = []  # 逐题明细，写进 result.json 方便复查
        for row in labels:  # 逐题检索
            nodes = retriever.retrieve(row["question"])  # 返回按相似度排序的 NodeWithScore
            names = [doc_name(n) for n in nodes]  # 召回片段的文件名，按排名顺序
            expected = row["expected_doc"]  # 期望文档名
            rank = names.index(expected) + 1 if expected in names else None  # 先 in 再 index；找不到是 None，直接 index 会 ValueError
            clause = any(  # 片段级命中：任一片段同时满足两个条件
                doc_name(n) == expected and row["expected_keyword"] in n.get_content()  # 来自期望文档 且 正文含关键句
                for n in nodes
            )
            hit += rank is not None  # True/False 当 1/0 加：命中文档 +1
            top1 += rank == 1  # 第 1 名就是期望文档 +1
            clause_hit += clause  # 片段级命中 +1
            mrr += 1 / rank if rank else 0  # 排名倒数；没命中记 0
            details.append(  # 记录本题明细
                {
                    "question": row["question"],  # 题目
                    "expected": expected,  # 期望文档
                    "rank": rank,  # 实际排名，None = 没召回
                    "clause": clause,  # 片段级是否命中
                    "got": names,  # 实际召回的文件名，方便看错在哪
                }
            )
        n = len(labels)  # 题目总数 = 12，作为分母
        item = {  # 本组配置的结果
            "chunk": chunk,  # 分段大小
            "top_k": k,  # TopK
            "doc_recall": round(hit / n, 3),  # 文档级召回率
            "top1_doc": round(top1 / n, 3),  # Top1 命中率
            "mrr": round(mrr / n, 3),  # 平均排名倒数
            "clause_recall": round(clause_hit / n, 3),  # 片段级召回率
            "details": details,  # 逐题明细
        }
        rows.append(item)  # 加入总表
        print(  # 控制台只打印汇总，不打印 details
            json.dumps(
                {x: item[x] for x in ("chunk", "top_k", "doc_recall", "top1_doc", "mrr", "clause_recall")},  # 字典推导：只挑 6 个汇总字段
                ensure_ascii=False,  # 保留中文
            )
        )

OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")  # 整体写盘：6 组 × 逐题明细
print(f"written {OUT}")  # 提示输出位置
