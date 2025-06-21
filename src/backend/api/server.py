# src/api/server.py
from fastapi import FastAPI
from pydantic import BaseModel
from interfaces.cli import run  # your existing entry-point
from langchain.agents import initialize_agent
from camel_ai import CamelAgent, ChatMemory

app = FastAPI()
memory = ChatMemory()
agent  = initialize_agent(
    agent_cls=CamelAgent,
    memory=memory,
    tools=[]            # add LangChain tools here
)

class ChatRequest(BaseModel):
    message: str

@app.post("/chat")
async def chat(req: ChatRequest):
    response = await agent.arun(req.message)
    return {"reply": response}
