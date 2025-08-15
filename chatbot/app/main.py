# main.py
from fastapi import FastAPI, Body
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from agent import call_agent

app = FastAPI(title="AI Assistant API", version="0.1.0")

class User(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None

class ChatRequest(BaseModel):
    text: str = Field(..., description="사용자 입력")
    user: Optional[User] = None

class Action(BaseModel):
    label: str
    url: str

class Citation(BaseModel):
    source: str
    snippet: str

class ChatResponse(BaseModel):
    reply: str
    actions: List[Action] = []
    citations: List[Citation] = []
    meta: Dict[str, Any] = {}

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest = Body(...)):
    return call_agent(req.model_dump())

@app.get("/healthz")
def healthz():
    return {"ok": True}
