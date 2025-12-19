# apps/backend/app/api/debug_rag.py
from __future__ import annotations

from fastapi import APIRouter, Request, Query
from typing import Any, Dict, Optional

router = APIRouter()

def _get_collection(store: Any):
    """
    Best-effort access to the underlying chromadb Collection.
    Adjust if your ChromaMemoryStore uses a different attribute name.
    """
    for attr in ("collection", "_collection", "col", "_col"):
        col = getattr(store, attr, None)
        if col is not None:
            return col
    return None

@router.get("/debug/rag/counts")
def rag_counts(request: Request):
    store = request.app.state.memory
    col = _get_collection(store)

    types = [
        "product_vision",
        "technical_solution",
        "ra_plan",
        "qa_spec",
        "design_notes",
        "story_tasks",
    ]

    out: Dict[str, Any] = {
        "store_class": type(store).__name__,
        "has_collection": bool(col),
        "counts": {},
        "samples": {},
    }

    if not col:
        out["error"] = "Could not access underlying chroma collection (no known attr: collection/_collection/col/_col)."
        return out

    # Total count (if supported)
    try:
        out["total"] = col.count()
    except Exception as e:
        out["total_error"] = f"{type(e).__name__}: {e}"

    # Per-type counts + sample metas
    for t in types:
        try:
            got = col.get(where={"type": t}, include=["metadatas", "documents"], limit=3)
            ids = got.get("ids", []) or []
            metas = got.get("metadatas", []) or []
            docs = got.get("documents", []) or []

            out["counts"][t] = len(ids)
            out["samples"][t] = [
                {
                    "id": ids[i],
                    "meta": metas[i] if i < len(metas) else None,
                    "doc_preview": (docs[i][:200] + "…") if (i < len(docs) and isinstance(docs[i], str) and len(docs[i]) > 200) else (docs[i] if i < len(docs) else None),
                }
                for i in range(min(3, len(ids)))
            ]
        except Exception as e:
            out["counts"][t] = f"ERROR {type(e).__name__}: {e}"
            out["samples"][t] = []

    return out

@router.get("/debug/rag/get")
def rag_get(
    request: Request,
    artifact_type: str = Query(..., description="artifact type, e.g. technical_solution"),
    limit: int = Query(5, ge=1, le=50),
):
    store = request.app.state.memory
    col = _get_collection(store)
    if not col:
        return {"error": "Could not access underlying chroma collection."}

    got = col.get(where={"type": artifact_type}, include=["metadatas", "documents"], limit=limit)
    ids = got.get("ids", []) or []
    metas = got.get("metadatas", []) or []
    docs = got.get("documents", []) or []

    return {
        "store_class": type(store).__name__,
        "artifact_type": artifact_type,
        "n": len(ids),
        "rows": [
            {
                "id": ids[i],
                "meta": metas[i] if i < len(metas) else None,
                "doc_preview": (docs[i][:400] + "…")
                if (i < len(docs) and isinstance(docs[i], str) and len(docs[i]) > 400)
                else (docs[i] if i < len(docs) else None),
            }
            for i in range(len(ids))
        ],
    }



@router.get("/debug/rag/query")
def rag_query(
    request: Request,
    artifact_type: str = Query(...),
    q: str = Query(..., description="query text"),
    top_k: int = Query(5, ge=1, le=50),
):
    store = request.app.state.memory
    col = _get_collection(store)
    if not col:
        return {"error": "Could not access underlying chroma collection."}

    res = col.query(
        query_texts=[q],
        n_results=top_k,
        where={"type": artifact_type},
        include=["metadatas", "documents", "distances"],
    )

    ids = (res.get("ids") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    rows = []
    for i in range(len(ids or [])):
        doc = docs[i] if i < len(docs) else None
        rows.append({
            "id": ids[i],
            "distance": dists[i] if i < len(dists) else None,
            "meta": metas[i] if i < len(metas) else None,
            "doc_preview": (doc[:400] + "…") if isinstance(doc, str) and len(doc) > 400 else doc,
        })

    return {
        "store_class": type(store).__name__,
        "artifact_type": artifact_type,
        "query_len": len(q),
        "n": len(rows),
        "rows": rows,
    }