from dotenv import load_dotenv
load_dotenv()

import os
from typing import List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .agents.agent import run_agent

def _compute_allowed_origins() -> List[str]:
    """
    Reads FRONTEND_ORIGIN from env; supports comma-separated list for future flexibility.
    Falls back to safe dev defaults when not set.
    """
    raw = os.getenv("FRONTEND_ORIGIN", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    # Dev-friendly defaults
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

app = FastAPI(title="Claire AI back-end")

# ----- CORS -----
ALLOWED_ORIGINS = _compute_allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Schemas -----
class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str

# ----- Health check -----
@app.get("/health")
async def health():
    return {"status": "ok"}

# ----- Chat -----
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        reply = run_agent(req.message)
        return ChatResponse(reply=reply if isinstance(reply, str) else str(reply))
    except Exception as e:
        import traceback, sys
        print("ERROR in /chat:", e, file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))
