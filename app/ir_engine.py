import os
import time
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.parsers import (
    DOCS_FOLDER, load_documents, preprocess, normalize_for_index,
    filter_stopwords, extract_snippet, extract_snippet_phrase
)
from app.bm25 import BM25Simple
from app.semantic_engine import SemanticEngine
from app.cache_manager import CacheManager

class IREngine:
    def __init__(self):
        self.semantic_engine = SemanticEngine()
        self.current_folder = DOCS_FOLDER
        self.recursive = False
        self.docs_raw, self.doc_names, self.doc_paths = load_documents(DOCS_FOLDER)
        self._build()

    def load_from_folder(self, folder_path, recursive=False):
        """Load documents from a specific folder"""
        if os.path.isdir(folder_path):
            self.current_folder = folder_path
            self.recursive = recursive
            self.docs_raw, self.doc_names, self.doc_paths = load_documents(folder_path, recursive=recursive)
            self._build()
            return True
        return False

    def _build(self):
        t0 = time.time()
        is_valid, cached = CacheManager.is_cache_valid(self.current_folder, self.doc_paths)

        if is_valid and cached is not None:
            self.docs_raw = cached.get("docs_raw", self.docs_raw)
            self.doc_names = cached.get("doc_names", self.doc_names)
            self.doc_paths = cached.get("doc_paths", self.doc_paths)
            self.docs_tokens = cached.get("doc_tokens", [])
            cached_embeddings = cached.get("doc_embeddings", None)
            
            self.vectorizer = TfidfVectorizer(stop_words="english")
            try:
                if self.docs_raw:
                    self.doc_vectors = self.vectorizer.fit_transform(self.docs_raw)
                else:
                    self.doc_vectors = None
            except Exception:
                self.doc_vectors = None

            self.bm25 = BM25Simple(self.docs_tokens) if self.docs_tokens else None
            self.semantic_engine.set_cached_embeddings(self.docs_raw, cached_embeddings)
            print(f"[IREngine] Instant cache load completed in {time.time() - t0:.3f}s for {len(self.docs_raw)} documents.")
            return

        # Cold build / cache miss
        self.vectorizer = TfidfVectorizer(stop_words="english")
        try:
            if self.docs_raw:
                self.doc_vectors = self.vectorizer.fit_transform(self.docs_raw)
            else:
                self.doc_vectors = None
        except Exception:
            self.doc_vectors = None

        self.docs_tokens = [normalize_for_index(d).split() for d in self.docs_raw]
        self.bm25 = BM25Simple(self.docs_tokens) if self.docs_tokens else None
        
        try:
            self.semantic_engine.build_index(self.docs_raw)
        except Exception as e:
            print(f"[IREngine] Semantic index build warning: {e}")

        # Save cache for future instant loads
        if self.doc_paths and self.docs_raw:
            CacheManager.save_cache(
                self.current_folder,
                self.doc_paths,
                self.docs_raw,
                self.doc_names,
                self.docs_tokens,
                self.semantic_engine.doc_embeddings
            )
        print(f"[IREngine] Full index build & cache save completed in {time.time() - t0:.3f}s.")

    def refresh(self):
        self.docs_raw, self.doc_names, self.doc_paths = load_documents(self.current_folder, recursive=self.recursive)
        self._build()

    def search(self, query, method="tfidf", top_k=10):
        is_exact_phrase = query.strip().startswith('"') and query.strip().endswith('"')
        
        if is_exact_phrase:
            phrase_query = query.strip()[1:-1]
            return self._search_exact_phrase(phrase_query, top_k)
        
        query_plain = preprocess(query)
        query_norm = normalize_for_index(query_plain)
        raw_tokens = [t for t in query_norm.split() if t]
        q_tokens = filter_stopwords(raw_tokens)
        
        if not q_tokens:
            q_tokens = raw_tokens
        
        results = []
        method_lower = method.lower()

        if method_lower == "hybrid":
            results = self._search_hybrid(query_plain, q_tokens, top_k)
        elif method_lower == "bm25" and self.bm25:
            scores = self.bm25.score(q_tokens)
            ranked = np.argsort(scores)[::-1]
            for idx in ranked[:top_k]:
                if scores[idx] > 0:
                    results.append((idx, float(scores[idx])))
        else:
            if self.doc_vectors is None:
                return []
            try:
                q_vec = self.vectorizer.transform([query_plain])
                sims = cosine_similarity(q_vec, self.doc_vectors)[0]
            except Exception:
                if self.bm25:
                    scores = self.bm25.score(q_tokens)
                    ranked = np.argsort(scores)[::-1]
                    for idx in ranked[:top_k]:
                        if scores[idx] > 0:
                            results.append((idx, float(scores[idx])))
                else:
                    return []
            else:
                ranked = np.argsort(sims)[::-1]
                for idx in ranked[:top_k]:
                    if sims[idx] > 0:
                        results.append((idx, float(sims[idx])))
        
        enriched = []
        for idx, score in results:
            snippet = extract_snippet(self.docs_raw[idx], q_tokens)
            enriched.append({
                "index": idx,
                "name": self.doc_names[idx],
                "path": self.doc_paths[idx],
                "score": round(score, 4),
                "snippet": snippet
            })
        return enriched

    def _search_hybrid(self, query_plain, q_tokens, top_k=10):
        rrf_scores = {}
        k_const = 60

        if self.bm25:
            bm25_scores = self.bm25.score(q_tokens)
            bm25_ranked = np.argsort(bm25_scores)[::-1]
            rank = 1
            for idx in bm25_ranked:
                if bm25_scores[idx] > 0:
                    rrf_scores[idx] = rrf_scores.get(idx, 0.0) + (1.0 / (k_const + rank))
                    rank += 1

        semantic_results = self.semantic_engine.search(query_plain, top_k=len(self.docs_raw))
        for rank, (idx, sem_score) in enumerate(semantic_results, start=1):
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + (1.0 / (k_const + rank))

        if not rrf_scores and self.doc_vectors is not None:
            try:
                q_vec = self.vectorizer.transform([query_plain])
                sims = cosine_similarity(q_vec, self.doc_vectors)[0]
                ranked = np.argsort(sims)[::-1]
                for rank, idx in enumerate(ranked, start=1):
                    if sims[idx] > 0:
                        rrf_scores[idx] = rrf_scores.get(idx, 0.0) + (1.0 / (k_const + rank))
            except Exception:
                pass

        sorted_rrf = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_rrf[:top_k]

    def _search_exact_phrase(self, phrase, top_k=10):
        phrase_lower = phrase.lower()
        results = []
        
        for idx, doc in enumerate(self.docs_raw):
            doc_lower = doc.lower()
            if phrase_lower in doc_lower:
                count = doc_lower.count(phrase_lower)
                first_pos = doc_lower.find(phrase_lower)
                position_score = 1.0 - (first_pos / max(len(doc), 1000)) * 0.5
                frequency_score = min(count / 10.0, 1.0)
                score = (position_score * 0.4 + frequency_score * 0.6)
                results.append((idx, score, count))
        
        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:top_k]
        
        enriched = []
        for idx, score, count in results:
            snippet = extract_snippet_phrase(self.docs_raw[idx], phrase)
            enriched.append({
                "index": idx,
                "name": self.doc_names[idx],
                "path": self.doc_paths[idx],
                "score": round(score, 4),
                "snippet": snippet,
                "phrase_matches": count
            })
        return enriched

    def top_keywords(self, doc_id, top_n=10):
        if self.doc_vectors is None:
            return []
        if doc_id < 0 or doc_id >= self.doc_vectors.shape[0]:
            return []
        try:
            features = self.vectorizer.get_feature_names_out()
        except Exception:
            features = self.vectorizer.get_feature_names()
        vec = self.doc_vectors[doc_id]
        if hasattr(vec, "toarray"):
            arr = np.asarray(vec.toarray()).ravel()
        else:
            try:
                arr = np.asarray(vec.todense()).ravel()
            except Exception:
                return []
        if arr.sum() == 0:
            return []
        inds = np.argsort(arr)[::-1][:top_n]
        kws = []
        for i in inds:
            if arr[i] > 0:
                kws.append(f"{features[i]} ({arr[i]:.4f})")
        return kws
