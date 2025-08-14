from dotenv import load_dotenv 

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .agents.agent import run_agent


app = FastAPI(title="Claire AI back-end")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # allow all for dev
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        reply = run_agent(req.message)
        return ChatResponse(reply=reply if isinstance(reply, str) else str(reply))
    except Exception as e:
        import traceback
        print("ERROR in /chat:", e)
        print(traceback.format_exc())
        # Return the original message to the client for debugging (dev only)
        raise HTTPException(status_code=500, detail=str(e))

