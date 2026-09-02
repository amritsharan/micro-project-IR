import os
import pickle

CACHE_FILENAME = ".index_cache.pkl"

class CacheManager:
    @staticmethod
    def _get_cache_path(folder_path):
        return os.path.join(folder_path, CACHE_FILENAME)

    @staticmethod
    def get_folder_manifest(doc_paths):
        """Build manifest of file paths and modification timestamps"""
        manifest = {}
        for p in doc_paths:
            if os.path.exists(p):
                manifest[p] = os.path.getmtime(p)
        return manifest

    @classmethod
    def is_cache_valid(cls, folder_path, doc_paths):
        cache_path = cls._get_cache_path(folder_path)
        if not os.path.exists(cache_path):
            return False, None

        try:
            with open(cache_path, "rb") as f:
                cached_data = pickle.load(f)

            cached_manifest = cached_data.get("manifest", {})
            current_manifest = cls.get_folder_manifest(doc_paths)

            if cached_manifest == current_manifest and len(cached_manifest) > 0:
                return True, cached_data
            return False, None
        except Exception as e:
            print(f"[CacheManager] Cache read error: {e}")
            return False, None

    @classmethod
    def save_cache(cls, folder_path, doc_paths, docs_raw, doc_names, doc_tokens, doc_embeddings):
        cache_path = cls._get_cache_path(folder_path)
        manifest = cls.get_folder_manifest(doc_paths)
        data = {
            "manifest": manifest,
            "doc_paths": doc_paths,
            "docs_raw": docs_raw,
            "doc_names": doc_names,
            "doc_tokens": doc_tokens,
            "doc_embeddings": doc_embeddings
        }
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(data, f)
            print(f"[CacheManager] Saved index cache to {cache_path}")
        except Exception as e:
            print(f"[CacheManager] Failed to save cache: {e}")
