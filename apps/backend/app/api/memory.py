from __future__ import annotations
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from app.configs.settings import get_settings
from app.core.memory import MemoryDoc  # safe; no circular import

from sqlalchemy.orm import Session
from app.storage.db import get_db              # same dep you use elsewhere
from app.storage.models import RequirementORM

router = APIRouter(prefix="/memory", tags=["memory"])

class ArtifactIn(BaseModel):
    type: Literal["requirement", "product_vision", "technical_solution"]
    title: Optional[str] = None
    text: str = Field(min_length=1)

class IngestRequest(BaseModel):
    run_id: str
    artifacts: List[ArtifactIn]

@router.get("/config")
def get_config(settings = Depends(get_settings)):
    return {
        "mode": settings.RAG_MODE,
        "collection": settings.RAG_COLLECTION,
        "top_k": settings.RAG_TOP_K,
    }

@router.post("/ingest")
def ingest(req: IngestRequest, request: Request, settings = Depends(get_settings), db: Session = Depends(get_db)):
    if settings.RAG_MODE.lower() == "off":
        raise HTTPException(status_code=403, detail="RAG_MODE=off — ingestion disabled")
    if not req.artifacts:
        return {"ok": True, "added": 0}
    
    # fetch requirement title once
    req_row = db.query(RequirementORM).filter_by(run_id=req.run_id).first()
    req_title = req_row.title if req_row else ""

    import uuid
    docs: List[MemoryDoc] = []
    for a in req.artifacts:
        # make PV/TS titles descriptive; keep requirement title as-is
        if a.type == "product_vision" and req_title:
            title = f"{req_title} — Product Vision"
        elif a.type == "technical_solution" and req_title:
            title = f"{req_title} — Technical Solution"
        else:
            title = a.title or req_title or ""

        docs.append(MemoryDoc(
        id=f"{req.run_id}:{a.type}:{uuid.uuid4().hex[:8]}",
        text=a.text,
        meta={
            "run_id": req.run_id,
            "type": a.type,
            "title": title,          # human-friendly title
            "req_title": req_title,  # <- requirement title for logging & RAG labels
            },
        ))

    store = request.app.state.memory
    store.add(docs)
    return {"ok": True, "added": len(docs)}

@router.post("/purge")
def purge(request: Request, settings = Depends(get_settings)):
    # Allow only in debug/dev
    if not getattr(settings, "DEBUG", False):
        raise HTTPException(status_code=403, detail="Purge allowed only when DEBUG=true")
    request.app.state.memory.purge()
    return {"ok": True}

@router.get("/status")
def rag_status(request: Request, settings = Depends(get_settings)):
    store = request.app.state.memory
    return {
        "mode": settings.RAG_MODE,
        "collection": settings.RAG_COLLECTION,
        "top_k": settings.RAG_TOP_K,
        "use_rag": settings.USE_RAG,
        "store": type(store).__name__,
    }

@router.get("/search")
def dev_search(request: Request, q: str = Query(...)):
    hits = request.app.state.memory.search(q, top_k=5)
    return [{"id": h.id, "meta": h.meta, "text": h.text[:160]} for h in hits]
