# apps/backend/app/main.py
from __future__ import annotations

# Load env early
from dotenv import load_dotenv
load_dotenv()

import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Settings + new Runs API
from app.core.memory import get_memory_store
from app.configs.settings import get_settings
from app.api.memory import router as memory_router
from app.api.runs import router as runs_router
from app.api.plan import router as plan_router
from app.api.runs_qol import router as runs_qol_router

settings = get_settings()

# ----- CORS helpers -----
def _compute_allowed_origins() -> List[str]:
    """
    Reads FRONTEND_ORIGIN from env (or settings); supports comma-separated list.
    Falls back to safe dev defaults.
    """
    raw = os.getenv("FRONTEND_ORIGIN", "").strip() or (str(settings.FRONTEND_ORIGIN) if settings.FRONTEND_ORIGIN else "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    # Dev-friendly defaults
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

app = FastAPI(title=settings.APP_NAME)

@app.on_event("startup")
async def _startup() -> None:
    app.state.memory = get_memory_store(
        path=settings.RAG_STORE_PATH,
        collection=settings.RAG_COLLECTION,
        mode=settings.RAG_MODE,
    )

# ----- CORS -----
ALLOWED_ORIGINS = _compute_allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Legacy chat schema (optional) =====
class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str

# Try to import your existing agent; if not present, we'll 501 the route.
_run_agent = None
try:
    # Keep your original import path if it still exists
    from .agents.agent import run_agent as _run_agent  # type: ignore
except Exception:
    _run_agent = None

# ----- Health check -----
@app.get("/health")
async def health():
    return {"status": "ok"}

# ----- Root (optional) -----
@app.get("/")
async def root():
    return {"name": settings.APP_NAME, "env": os.getenv("ENV", "dev")}

# ----- Chat (kept for compatibility) -----
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if _run_agent is None:
        raise HTTPException(status_code=501, detail="Chat agent not available in M1.1 scaffold")
    try:
        reply = _run_agent(req.message)
        return ChatResponse(reply=reply if isinstance(reply, str) else str(reply))
    except Exception as e:
        import traceback, sys
        print("ERROR in /chat:", e, file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))

# ----- M1.1: Runs API -----
# Exposes:
#   POST /runs         -> create run + manifest + save requirement
#   GET  /runs/{id}    -> fetch run + manifest + requirement
app.include_router(runs_router)
app.include_router(plan_router)
app.include_router(runs_qol_router)
app.include_router(memory_router)
