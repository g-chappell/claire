# apps/backend/app/core/memory.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence, Mapping, cast, TYPE_CHECKING

if TYPE_CHECKING:
    # Only for the type checker; no runtime import
    from chromadb.api.types import IDs, Documents, Embeddings, Metadatas, Metadata, Include

@dataclass
class MemoryDoc:
    id: str
    text: str
    meta: Dict[str, str]  # e.g., {"run_id": "...", "type": "product_vision", "title": "..."}

class MemoryStore(Protocol):
    """Interface for vector memory."""
    def add(self, docs: List[MemoryDoc]) -> None: ...
    def search(
        self,
        query: str,
        top_k: int = 6,
        where: Optional[Dict] = None,
        min_similarity: Optional[float] = None,
        ) -> List[MemoryDoc]: ...
    def purge(self) -> None: ...

class NoOpMemoryStore:
    """Safe placeholder: does nothing until we wire a real backend (PR-B/C)."""
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def add(self, docs: List[MemoryDoc]) -> None:
        # no-op
        return

    def search(self, query: str, top_k: int = 6, where: Optional[Dict] = None, min_similarity: Optional[float] = None) -> List[MemoryDoc]:
        # no results in skeleton mode
        return []

    def purge(self) -> None:
        # nothing to purge
        return

class ChromaMemoryStore:
    def __init__(self, path: str, collection: str, embed_model: str = "all-MiniLM-L6-v2"):
        # lazy imports to avoid deps when RAG is off
        import os
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")

        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.PersistentClient(
            path=path,
            settings=Settings(anonymized_telemetry=False),
        )
        from sentence_transformers import SentenceTransformer  # type: ignore
        self._collection_name = collection
        self._col = self._client.get_or_create_collection(name=self._collection_name)
        self._embedder = SentenceTransformer(embed_model)

    def _embed(self, texts: List[str]) -> List[List[float]]:
        # Handle Tensor or ndarray or list return types
        arr = self._embedder.encode(texts, normalize_embeddings=True)
        try:
            # ndarray / torch.Tensor path
            return arr.tolist()  # type: ignore[union-attr]
        except AttributeError:
            # Some versions already return a python list
            return arr  # type: ignore[return-value]

    def add(self, docs: List[MemoryDoc]) -> None:
        if not docs: return
        ids: List[str] = [d.id for d in docs]
        documents: List[str] = [d.text for d in docs]
        # keep metadata values as strings to match Dict[str, str]
        metas_list: List[Dict[str, str]] = [d.meta for d in docs]
        embeds_list: List[List[float]] = self._embed(documents)

        # Cast to Chroma’s typed aliases so Pylance is happy
        ids_t: "IDs" = cast("IDs", ids)
        docs_t: "Documents" = cast("Documents", documents)
        metas_t: "Metadatas" = cast("Metadatas", metas_list)           # List[Metadata]
        embeds_t: "Embeddings" = cast("Embeddings", embeds_list)       # List[Embedding]

        self._col.add(ids=ids_t, documents=docs_t, metadatas=metas_t, embeddings=embeds_t)

    def search(
        self,
        query: str,
        top_k: int = 6,
        where: Optional[Dict] = None,
        min_similarity: Optional[float] = None,
    ) -> List[MemoryDoc]:
        q_emb = self._embed([query])[0]
        include_t: "Include" = cast("Include", ["documents", "metadatas", "distances"])
        res = self._col.query(
            query_embeddings=[q_emb],
            n_results=top_k,
            where=where or {},
            include=include_t,
        )
        out: List[MemoryDoc] = []
        ids = res.get("ids") or []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        dists = res.get("distances") or []
        if not ids or not ids[0]:
            return out
        ids0  = cast(List[str], ids[0])
        docs0 = cast(List[str], docs[0]) if docs else []
        metas0 = cast(List[Mapping[str, Any]], metas[0]) if metas else []
        dists0 = cast(List[float], dists[0]) if dists else []
        for i, _id in enumerate(ids0):
            # Convert distance -> similarity (cosine metric): sim = 1 - dist
            sim = 1.0 - (dists0[i] if i < len(dists0) else 1.0)
            if min_similarity is not None and sim < min_similarity:
                continue
            meta_dict: Dict[str, str] = {str(k): str(v) for k, v in (metas0[i] if i < len(metas0) else {}).items()}
            out.append(MemoryDoc(
                id=_id,
                text=docs0[i] if i < len(docs0) else "",
                meta=meta_dict,
            ))
        return out

    def purge(self) -> None:
        # Preferred: drop and recreate the collection
        try:
            self._client.delete_collection(self._collection_name)
        except Exception:
            # Fallback: delete by IDs if delete_collection isn't available
            try:
                got = self._col.get(limit=100000, include=[])  # ids only
                ids = got.get("ids") or []
                # Some versions return nested lists; flatten if needed
                if ids and isinstance(ids[0], list):
                    ids = ids[0]
                if ids:
                    self._col.delete(ids=ids)
            except Exception:
                pass
        # Recreate a fresh, empty collection
        self._col = self._client.get_or_create_collection(name=self._collection_name)

def get_memory_store(path: str = "./data/vector", collection: str = "claire-dev", mode: str = "off"):
    # Off -> NoOp; any other mode -> real store
    if str(mode).lower() == "off":
        return NoOpMemoryStore()
    try:
        return ChromaMemoryStore(path=path, collection=collection)
    except Exception:
        # Fallback to NoOp if deps are missing
        return NoOpMemoryStore()

