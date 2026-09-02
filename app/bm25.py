from math import log

class BM25Simple:
    def __init__(self, docs_tokens):
        self.docs_tokens = docs_tokens
        self.N = len(docs_tokens)
        self.avgdl = sum(len(d) for d in docs_tokens) / self.N if self.N else 0.0
        self.doc_freqs = []
        self.df = {}
        for doc in docs_tokens:
            freqs = {}
            for w in doc:
                freqs[w] = freqs.get(w, 0) + 1
            self.doc_freqs.append(freqs)
            for w in freqs.keys():
                self.df[w] = self.df.get(w, 0) + 1
        self.idf = {}
        for w, freq in self.df.items():
            self.idf[w] = log(1 + (self.N - freq + 0.5) / (freq + 0.5))
        self.k1 = 1.5
        self.b = 0.75

    def score(self, query_tokens):
        scores = [0.0] * self.N
        for q in query_tokens:
            if q not in self.idf:
                continue
            idf = self.idf[q]
            for i in range(self.N):
                tf = self.doc_freqs[i].get(q, 0)
                if tf == 0:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * (len(self.docs_tokens[i]) / self.avgdl))
                scores[i] += idf * (tf * (self.k1 + 1)) / denom
        return scores
