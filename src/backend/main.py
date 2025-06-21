from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent import run_agent

app = FastAPI(title="Claire AI back-end")

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        reply = run_agent(req.message)
        return ChatResponse(reply=reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
