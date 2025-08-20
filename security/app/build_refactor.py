# =============================
# build_index.py (FAISS + LangChain, dual-embedding)
#   - 텍스트: intfloat/multilingual-e5-large (SentenceTransformers)
#   - 코드   : OpenAI text-embedding-3-large
#   - LangChain 사용: Embeddings 인터페이스 + FAISS VectorStore 저장
#   - 입력: data/security_guides.json(.jsonl)  (sections: overview/mitigation/references/unsafe_examples/safe_examples)
#   - 출력: index/faiss_text_lc/ , index/faiss_code_lc/ (LangChain 포맷)
# =============================
import os, json, re, time, uuid, argparse
from pathlib import Path
from typing import List, Dict, Any, Iterable

import numpy as np
from sentence_transformers import SentenceTransformer
from openai import OpenAI

from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
DATA_JSON  = Path(os.getenv("DATA_JSON",  DATA_DIR / "security_guides.json"))
DATA_JSONL = Path(os.getenv("DATA_JSONL", DATA_DIR / "security_guides.jsonl"))

INDEX_DIR = BASE / "index"
TEXT_STORE_DIR = INDEX_DIR / "faiss_text_lc"
CODE_STORE_DIR = INDEX_DIR / "faiss_code_lc"
TEXT_STORE_DIR.mkdir(parents=True, exist_ok=True)
CODE_STORE_DIR.mkdir(parents=True, exist_ok=True)

# 모델 설정 (환경변수로 override 가능)
TEXT_EMBED_MODEL = os.getenv("TEXT_EMBED_MODEL", "intfloat/multilingual-e5-large")
CODE_EMBED_MODEL = os.getenv("CODE_EMBED_MODEL", "text-embedding-3-large")
BATCH = int(os.getenv("BATCH", "32"))

# ---------------- 공용 유틸 ----------------
_norm = lambda s: re.sub(r"[^a-z0-9가-힣]","", (s or "").lower())

def _parse_json_or_jsonl_str(s: str):
    try:
        obj = json.loads(s)
        if isinstance(obj, list):
            return obj
        raise ValueError("not list")
    except Exception:
        items=[]
        for line in s.splitlines():
            line=line.strip()
            if line: items.append(json.loads(line))
        return items

def load_guides() -> List[Dict[str, Any]]:
    if DATA_JSON.exists():
        raw = DATA_JSON.read_text(encoding="utf-8")
        try:
            data = _parse_json_or_jsonl_str(raw)
            if raw.lstrip().startswith("{"):
                DATA_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return data
        except Exception:
            pass
    if DATA_JSONL.exists():
        data = _parse_json_or_jsonl_str(DATA_JSONL.read_text(encoding="utf-8"))
        DATA_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data
    raise FileNotFoundError("security_guides.json(.jsonl) 없음")

# ---------------- 섹션 → Documents ----------------
SECTIONS_TEXT = ["overview","mitigation","references"]
SECTIONS_CODE = ["unsafe_examples","safe_examples"]

def mk_docs(g: Dict[str, Any]) -> tuple[list[Document], list[Document]]:
    sid = g.get("security_id") or str(uuid.uuid4())
    sname = g.get("security_name", sid)
    secs = g.get("sections", {}) or {}
    docs_text: list[Document] = []
    docs_code: list[Document] = []

    def add_doc(target: list[Document], sec_key: str, text: str, *, is_code: bool):
        t = (text or "").strip()
        if not t:
            return
        meta = {
            "doc_id": f"{sid}#{sec_key}",
            "security_id": sid,
            "security_name": sname,
            "section": sec_key,
            "is_code": is_code,
            "lang": guess_lang(t) if is_code else "txt",
        }
        target.append(Document(page_content=t, metadata=meta))

    for sec in SECTIONS_TEXT:
        add_doc(docs_text, sec, secs.get(sec), is_code=False)
    for sec in SECTIONS_CODE:
        add_doc(docs_code, sec, secs.get(sec), is_code=True)

    return docs_text, docs_code

# 간단한 언어 추정 (코드)
def guess_lang(code: str) -> str:
    c = code or ""
    if re.search(r"\bpublic\s+class\b|System\.out\.println", c): return "java"
    if re.search(r"\bimport\s+\w+|def\s+\w+\(", c): return "python"
    if re.search(r"#include\s*<\w+>|int\s+main\s*\(", c): return "c"
    if re.search(r"function\s+\w+\(|console\.log", c): return "javascript"
    if re.search(r"SELECT\s+.+\s+FROM\b", c, re.I): return "sql"
    return "txt"

# ---------------- LangChain Embeddings ----------------
class E5EmbeddingsLC(Embeddings):
    """SentenceTransformer 기반 E5 (query/doc prefix 분리 + L2 정규화)."""
    def __init__(self, model_name: str):
        self.m = SentenceTransformer(model_name)
    def _encode(self, texts: List[str]) -> List[List[float]]:
        arr = self.m.encode(texts, normalize_embeddings=False, show_progress_bar=False)
        x = np.asarray(arr, dtype="float32")
        n = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
        return (x / n).tolist()
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._encode(["passage: "+t for t in texts])
    def embed_query(self, text: str) -> List[float]:
        return self._encode(["query: "+text])[0]

class OpenAIEmbeddingsLC(Embeddings):
    """OpenAI Embeddings (text-embedding-3-large) + L2 정규화."""
    def __init__(self, model: str):
        self.client = OpenAI()
        self.model = model
    def _embed(self, texts: List[str]) -> List[List[float]]:
        resp = self.client.embeddings.create(model=self.model, input=texts)
        x = np.asarray([d.embedding for d in resp.data], dtype="float32")
        n = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
        return (x / n).tolist()
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts)
    def embed_query(self, text: str) -> List[float]:
        return self._embed([text])[0]

# ---------------- main ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=BATCH)
    args = ap.parse_args()

    guides = load_guides()
    text_docs: List[Document] = []
    code_docs: List[Document] = []
    for g in guides:
        t, c = mk_docs(g)
        text_docs.extend(t)
        code_docs.extend(c)
    print(f"📦 guides: {len(guides)} | text_docs: {len(text_docs)} | code_docs: {len(code_docs)}")

    # LangChain Embeddings
    txt_emb = E5EmbeddingsLC(TEXT_EMBED_MODEL)
    cod_emb = OpenAIEmbeddingsLC(CODE_EMBED_MODEL)

    # VectorStore (FAISS)
    if text_docs:
        vs_text = FAISS.from_documents(text_docs, embedding=txt_emb)
        vs_text.save_local(str(TEXT_STORE_DIR))
        print(f"✅ TEXT store saved: {TEXT_STORE_DIR}")
    if code_docs:
        vs_code = FAISS.from_documents(code_docs, embedding=cod_emb)
        vs_code.save_local(str(CODE_STORE_DIR))
        print(f"✅ CODE store saved: {CODE_STORE_DIR}")

    print("🎉 build_index (LangChain+FAISS) done.")

if __name__ == "__main__":
    main()
