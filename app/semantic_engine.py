import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

class SemanticEngine:
    """
    Semantic Search Engine using Dense Vector Embeddings (Sentence Transformers).
    Computes 384-dimensional contextual embeddings for documents and queries.
    """
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self.doc_embeddings = None
        self.docs_raw = []

    def _lazy_init(self):
        if self.model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(self.model_name)
            except Exception as e:
                print(f"[SemanticEngine] Warning: Could not load SentenceTransformer ({e}).")
                self.model = False

    def set_cached_embeddings(self, docs_raw, embeddings):
        self.docs_raw = docs_raw
        self.doc_embeddings = embeddings

    def build_index(self, docs_raw, cached_embeddings=None):
        self.docs_raw = docs_raw
        if not docs_raw:
            self.doc_embeddings = None
            return

        if cached_embeddings is not None and len(cached_embeddings) == len(docs_raw):
            self.doc_embeddings = cached_embeddings
            return

        self._lazy_init()
        if self.model:
            try:
                self.doc_embeddings = self.model.encode(
                    docs_raw,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    normalize_embeddings=True
                )
            except Exception as e:
                print(f"[SemanticEngine] Error encoding docs: {e}")
                self.doc_embeddings = None
        else:
            self.doc_embeddings = None

    def search(self, query, top_k=10):
        if self.doc_embeddings is None or len(self.docs_raw) == 0:
            return []

        self._lazy_init()
        if not self.model:
            return []

        try:
            q_emb = self.model.encode(
                [query],
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True
            )
            sims = cosine_similarity(q_emb, self.doc_embeddings)[0]
            ranked = np.argsort(sims)[::-1]

            results = []
            for idx in ranked[:top_k]:
                if sims[idx] > 0:
                    results.append((idx, float(sims[idx])))
            return results
        except Exception as e:
            print(f"[SemanticEngine] Search error: {e}")
            return []
