# apps/backend/app/core/memory.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence, Mapping, cast, TYPE_CHECKING
import hashlib

if TYPE_CHECKING:
    # Only for the type checker; no runtime import
    from chromadb.api.types import IDs, Documents, Embeddings, Metadatas, Metadata, Include

import logging
logger = logging.getLogger(__name__)

@dataclass
class MemoryDoc:
    id: str
    text: str
    meta: Dict[str, str]  # e.g., {"run_id": "...", "type": "product_vision", "title": "..."}
    # Optional text used ONLY for embeddings (similarity search). Stored document text remains `text`.
    embed_text: Optional[str] = None

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

    # NEW: delete by metadata filter (used for overwrite semantics)
    def delete_where(self, where: Dict) -> int: ...

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
    
    def delete_where(self, where: Dict) -> int:
        return 0

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

        # Prefer cosine for normalized embeddings. NOTE: if collection already exists,
        # Chroma will keep its existing space.
        self._col = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        # Capture the actual space for correct distance->similarity conversion.
        try:
            self._space = str((getattr(self._col, "metadata", None) or {}).get("hnsw:space", "l2")).lower()
        except Exception:
            self._space = "l2"

        logger.info("CHROMA_INIT collection=%s space=%s embed_model=%s", self._collection_name, self._space, embed_model)

        self._embedder = SentenceTransformer(embed_model)

    def _embed(self, texts: List[str]) -> List[List[float]]:
        # Handle Tensor or ndarray or list return types
        if texts:
            sample = (texts[0] or "").replace("\n", "\\n")
            logger.info(
                "CHROMA_EMBED n=%d sample_len=%d sample_sha1=%s sample_prev=%s",
                len(texts),
                len(texts[0] or ""),
                hashlib.sha1((texts[0] or "").encode("utf-8")).hexdigest()[:10],
                (sample[:239] + "…") if len(sample) > 240 else sample,
            )

        arr = self._embedder.encode(texts, normalize_embeddings=True)
        try:
            # ndarray / torch.Tensor path
            return arr.tolist()  # type: ignore[union-attr]
        except AttributeError:
            # Some versions already return a python list
            return arr  # type: ignore[return-value]

    def add(self, docs: List[MemoryDoc]) -> None:
        if not docs:
            return

        ids: List[str] = [d.id for d in docs]
        documents: List[str] = [d.text for d in docs]  # stored payload (what gets injected)
        # keep metadata values as strings to match Dict[str, str]
        metas_list: List[Dict[str, str]] = [d.meta for d in docs]

        # IMPORTANT: similarity is computed on embed_text when provided, otherwise on stored text.
        embed_inputs: List[str] = [
            (getattr(d, "embed_text", None) or d.text) for d in docs
        ]
        embeds_list: List[List[float]] = self._embed(embed_inputs)

        # Light-weight debug so you can see experiment/run tags flowing through
        if metas_list:
            sample_meta = dict(metas_list[0])
        else:
            sample_meta = {}
        logger.debug(
            "MEM_ADD collection=%s docs=%d sample_meta_keys=%s",
            self._collection_name,
            len(docs),
            list(sample_meta.keys()),
        )

        # Cast to Chroma’s typed aliases so Pylance is happy
        ids_t: "IDs" = cast("IDs", ids)
        docs_t: "Documents" = cast("Documents", documents)
        metas_t: "Metadatas" = cast("Metadatas", metas_list)           # List[Metadata]
        embeds_t: "Embeddings" = cast("Embeddings", embeds_list)       # List[Embedding]

        self._col.add(ids=ids_t, documents=docs_t, metadatas=metas_t, embeddings=embeds_t)

    def _normalize_where(self, where: Optional[Dict]) -> Dict:
        """
        Chroma where-clause requirement (newer versions):
        - Must be a single operator at the top level (e.g. {"$and":[...]}),
        OR a single field constraint.
        If caller provides multiple field constraints, wrap in {"$and":[...]}.
        """
        if not where:
            return {}

        # Already operator-based at top-level -> pass through
        if any(str(k).startswith("$") for k in where.keys()):
            logger.info("CHROMA_WHERE where_in=%s where_norm=%s", where, where)
            return where

        # Convert {"a":1,"b":2} -> {"$and":[{"a":1},{"b":2}]}
        items = [{k: v} for k, v in where.items() if v is not None]
        if not items:
            return {}

        if len(items) == 1:
            norm = items[0]
            logger.info("CHROMA_WHERE where_in=%s where_norm=%s", where, norm)
            return norm

        norm = {"$and": items}
        logger.info("CHROMA_WHERE where_in=%s where_norm=%s", where, norm)
        return norm
    
    def _distance_to_similarity(self, dist: float) -> float:
        """
        Convert Chroma distance to an approximate cosine-similarity-like score.

        With normalize_embeddings=True:
        - cosine space: dist = 1 - cos_sim        => cos_sim = 1 - dist
        - l2 space:     dist = ||u - v|| (unit)   => cos_sim = 1 - (dist^2)/2
        """
        space = getattr(self, "_space", "l2")

        if space == "cosine":
            return 1.0 - dist

        if space in ("l2", "euclidean"):
            return 1.0 - (dist * dist) / 2.0

        # Fallback
        return 1.0 - dist

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
            where=self._normalize_where(where),
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
            dist = (dists0[i] if i < len(dists0) else 1.0)
            sim = self._distance_to_similarity(dist)

            # Helpful debug for first few candidates
            if i < 3:
                logger.info(
                    "CHROMA_SCORE space=%s id=%s dist=%.4f sim=%.4f min_sim=%s where=%s",
                    getattr(self, "_space", "unknown"),
                    _id,
                    float(dist),
                    float(sim),
                    min_similarity,
                    where,
                )

            if min_similarity is not None and sim < min_similarity:
                continue

            meta_dict: Dict[str, str] = {
                str(k): str(v)
                for k, v in (metas0[i] if i < len(metas0) else {}).items()
            }
            out.append(MemoryDoc(
                id=_id,
                text=docs0[i] if i < len(docs0) else "",
                meta=meta_dict,
            ))
        return out
    
    def delete_where(self, where: Dict) -> int:
        """
        Delete docs matching a Chroma metadata filter.
        Accepts either:
        - {"run_id": "...", "type": "..."}  (we'll convert to $and)
        - {"$and": [{"run_id": "..."}, {"type": "..."}]} (passed through)
        Returns the number of deleted docs.
        """
        if not where:
            return 0

        where_norm = self._normalize_where(where)
        if not where_norm:
            return 0

        try:
            got = self._col.get(where=where_norm, limit=100000)
            ids = got.get("ids") or []
            ids_list = cast(List[str], ids)
            if not ids_list:
                return 0

            ids_t: "IDs" = cast("IDs", ids_list)
            self._col.delete(ids=ids_t)
            return len(ids_list)
        except Exception:
            logger.exception("delete_where failed for where=%s (normalized=%s)", where, where_norm)
            return 0

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

