"""LlamaIndex 纯向量检索：3 种分段 × 2 种 TopK 的召回对比。

指标（逐题计算）：
- doc_recall：期望文档是否出现在 top-k（文档级）
- top1_doc：第 1 条召回是否来自期望文档
- mrr：期望文档第一次出现的排名倒数
- clause_recall：top-k 中是否存在「来自期望文档且包含答案关键句」的片段

注意口径：这里是纯向量（bge-small-zh），Dify 内置是混合检索（语义 + 关键词），
两者不能直接说谁更好，报告里必须写清楚。
"""

import csv
import json
import os
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from llama_index.core import SimpleDirectoryReader, Settings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

BASE = Path(__file__).resolve().parent.parent
LABELS = BASE / "rag" / "labels.csv"
OUT = BASE / "rag" / "result.json"

Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-zh-v1.5")
Settings.llm = None  # 只做检索，不生成

docs = SimpleDirectoryReader(str(BASE / "kb")).load_data()
labels = list(csv.DictReader(open(LABELS, encoding="utf-8-sig")))


def doc_name(node) -> str:
    return os.path.basename(node.metadata.get("file_name", ""))


rows = []
for chunk in (300, 500, 800):
    index = VectorStoreIndex.from_documents(
        docs,
        transformations=[SentenceSplitter(chunk_size=chunk, chunk_overlap=chunk // 10)],
    )
    for k in (3, 5):
        retriever = index.as_retriever(similarity_top_k=k)
        hit = top1 = clause_hit = 0
        mrr = 0.0
        details = []
        for row in labels:
            nodes = retriever.retrieve(row["question"])
            names = [doc_name(n) for n in nodes]
            expected = row["expected_doc"]
            rank = names.index(expected) + 1 if expected in names else None
            clause = any(
                doc_name(n) == expected and row["expected_keyword"] in n.get_content()
                for n in nodes
            )
            hit += rank is not None
            top1 += rank == 1
            clause_hit += clause
            mrr += 1 / rank if rank else 0
            details.append(
                {
                    "question": row["question"],
                    "expected": expected,
                    "rank": rank,
                    "clause": clause,
                    "got": names,
                }
            )
        n = len(labels)
        item = {
            "chunk": chunk,
            "top_k": k,
            "doc_recall": round(hit / n, 3),
            "top1_doc": round(top1 / n, 3),
            "mrr": round(mrr / n, 3),
            "clause_recall": round(clause_hit / n, 3),
            "details": details,
        }
        rows.append(item)
        print(
            json.dumps(
                {x: item[x] for x in ("chunk", "top_k", "doc_recall", "top1_doc", "mrr", "clause_recall")},
                ensure_ascii=False,
            )
        )

OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"written {OUT}")
