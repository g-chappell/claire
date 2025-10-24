from __future__ import annotations
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from app.configs.settings import get_settings
from app.core.memory import MemoryDoc  # safe; no circular import

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
def ingest(req: IngestRequest, request: Request, settings = Depends(get_settings)):
    if settings.RAG_MODE.lower() == "off":
        raise HTTPException(status_code=403, detail="RAG_MODE=off — ingestion disabled")
    if not req.artifacts:
        return {"ok": True, "added": 0}

    import uuid
    docs: List[MemoryDoc] = []
    for a in req.artifacts:
        docs.append(MemoryDoc(
            id=f"{req.run_id}:{a.type}:{uuid.uuid4().hex[:8]}",
            text=a.text,
            meta={"run_id": req.run_id, "type": a.type, "title": a.title or ""},
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
