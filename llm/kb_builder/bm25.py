"""BM25 关键词检索。中文用 jieba 分词；没装 jieba 时退化为字的二元组。"""
from __future__ import annotations

import gzip
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

try:
    import jieba

    jieba.setLogLevel(60)
except ImportError:  # pragma: no cover
    jieba = None

STOPWORDS = set(
    "的 了 是 在 和 与 及 或 也 就 都 而 被 把 对 从 到 为 以 于 之 其 这 那 这个 那个 一个 什么 怎么 如何 "
    "为什么 哪些 哪个 吗 呢 吧 啊 么 我 你 他 她 它 我们 你们 他们 有 没有 可以 能 会 要 请 问 "
    "a an the of to in on for and or is are was be with by as at it this that what how why which".split()
)
_WORD = re.compile(r"[a-z0-9][a-z0-9._+-]*|[一-鿿]+")


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens: list[str] = []
    for piece in _WORD.findall(text):
        if piece[0].isascii():
            tokens.append(piece)
        elif jieba is not None:
            tokens.extend(jieba.lcut_for_search(piece))
        else:
            tokens.extend(piece[i:i + 2] for i in range(max(1, len(piece) - 1)))
    return [t for t in tokens if t not in STOPWORDS and t.strip()]


class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.postings: dict[str, list[tuple[int, int]]] = {}
        self.doc_len: list[int] = []
        self.avgdl = 0.0

    def fit(self, texts: list[str]) -> "BM25":
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.doc_len = []
        for i, text in enumerate(texts):
            tf = Counter(tokenize(text))
            self.doc_len.append(sum(tf.values()))
            for term, n in tf.items():
                postings[term].append((i, n))
        self.postings = dict(postings)
        self.avgdl = sum(self.doc_len) / max(1, len(self.doc_len))
        return self

    def search(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        n_docs = len(self.doc_len)
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokenize(query)):
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = math.log(1 + (n_docs - len(plist) + 0.5) / (len(plist) + 0.5))
            for i, tf in plist:
                norm = tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                scores[i] += idf * tf * (self.k1 + 1) / norm
        return sorted(scores.items(), key=lambda x: -x[1])[:top_k]

    def save(self, path: Path) -> None:
        data = {"k1": self.k1, "b": self.b, "doc_len": self.doc_len, "postings": self.postings}
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path) -> "BM25":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        bm25 = cls(data["k1"], data["b"])
        bm25.doc_len = data["doc_len"]
        bm25.postings = {t: [tuple(p) for p in ps] for t, ps in data["postings"].items()}
        bm25.avgdl = sum(bm25.doc_len) / max(1, len(bm25.doc_len))
        return bm25
