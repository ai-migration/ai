# main.py
from fastapi import FastAPI, Body, UploadFile, File, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from app.agent import call_agent, RAG
import os, re, shutil

app = FastAPI(title="AI Assistant API", version="0.2.0")

# ---------- Chat ----------
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

# ---------- RAG: Upload / Reindex / Search / List ----------
ALLOWED_EXTS = {".txt", ".md", ".pdf",".docx"}
UPLOAD_DIR = os.path.join(RAG.knowledge_dir, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

def _sanitize_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", name)
    return name[:128]

class UploadResult(BaseModel):
    saved: List[str]
    indexed_chunks: int

@app.post("/api/rag/upload", response_model=UploadResult)
async def rag_upload(files: List[UploadFile] = File(...)):
    saved_paths: List[str] = []
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in ALLOWED_EXTS:
            continue
        safe = _sanitize_filename(f.filename or f"doc{len(saved_paths)}{ext}")
        path = os.path.join(UPLOAD_DIR, safe)
        with open(path, "wb") as out:
            shutil.copyfileobj(f.file, out)
        saved_paths.append(path)

    chunks = RAG.ingest_files(saved_paths)
    return UploadResult(saved=[os.path.basename(p) for p in saved_paths], indexed_chunks=chunks)

@app.post("/api/rag/reindex")
async def rag_reindex():
    RAG.rebuild()
    return {"ok": True, "message": "reindexed"}

@app.get("/api/rag/list")
async def rag_list():
    return {"files": RAG.list_files()}

@app.get("/api/rag/search")
async def rag_search(q: str = Query(...), k: int = Query(4, ge=1, le=20)):
    return {"results": RAG.retrieve(q, k=k)}
