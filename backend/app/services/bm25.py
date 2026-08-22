"""Dependency-free BM25. Always available, so search never hard-depends on a model download."""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9+#.]+")

# Resume-speak: keep short tech tokens (go, c, r, ai, ml) but drop filler.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "he", "in", "is", "it", "its", "of", "on", "or", "that", "the", "to", "was",
    "were", "will", "with", "you", "your", "i", "me", "my", "we", "us", "do",
    "does", "did", "what", "which", "who", "how", "why", "when", "can", "would",
    "should", "could", "about", "tell", "please", "give", "any",
}


def tokenize(text: str) -> list[str]:
    tokens = _TOKEN.findall(text.lower())
    return [t.strip(".") for t in tokens if t not in STOPWORDS and len(t.strip(".")) > 1]


class BM25:
    """Standard Okapi BM25 over a small, in-memory corpus."""

    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs = [tokenize(doc) for doc in corpus]
        self.n = len(self.docs)
        self.doc_len = [len(d) for d in self.docs]
        self.avg_len = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.freqs = [Counter(d) for d in self.docs]

        df: Counter[str] = Counter()
        for doc in self.docs:
            df.update(set(doc))
        # +1 smoothing keeps idf positive even for terms present in every chunk.
        self.idf = {
            term: math.log(1 + (self.n - count + 0.5) / (count + 0.5))
            for term, count in df.items()
        }

    def search(self, query: str) -> list[float]:
        terms = tokenize(query)
        scores = [0.0] * self.n
        if not terms or not self.n:
            return scores
        for i, freq in enumerate(self.freqs):
            length = self.doc_len[i] or 1
            total = 0.0
            for term in terms:
                tf = freq.get(term)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * length / (self.avg_len or 1))
                total += self.idf.get(term, 0.0) * tf * (self.k1 + 1) / denom
            scores[i] = total
        return scores
