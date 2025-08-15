# agent.py
import os
import re
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv
load_dotenv()  # .env 로드

# 선택 의존성
try:
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from langchain_community.vectorstores import FAISS
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except Exception:
    ChatOpenAI = None
    OpenAIEmbeddings = None
    FAISS = None
    RecursiveCharacterTextSplitter = None

# PDF 텍스트 추출 (선택)
try:
    from pypdf import PdfReader  # pip install pypdf
except Exception:
    PdfReader = None

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# -------------------- 라우트 제안 규칙 --------------------
ROUTES = [
    {"label": "AI 변환기 소개", "url": "/support/transform/intro", "pat": r"(변환|transform).*(소개|intro)?"},
    {"label": "변환 하기", "url": "/support/transform/transformation", "pat": r"(변환(하기)?|transformation)"},
    {"label": "변환 이력 조회", "url": "/support/transform/view_transform", "pat": r"(변환.*(이력|기록)|view[_-]?transform)"},
    {"label": "테스트 이력 조회", "url": "/support/transform/view_test", "pat": r"(테스트.*(이력|기록)|view[_-]?test)"},
    {"label": "다운로드 (변환 산출물)", "url": "/support/transform/download", "pat": r"(다운로드|download)"},
    {"label": "AI 보안기 소개", "url": "/support/security/intro", "pat": r"(보안|security).*(소개|intro)"},
    {"label": "AI 보안 검사", "url": "/support/security/scan", "pat": r"(보안\s*(검사|스캔)|scan)"},
    {"label": "보안 취약점 탐지", "url": "/support/security/vulnerability", "pat": r"(취약점|vulnerability)"},
    {"label": "보안 점검결과", "url": "/support/security/report", "pat": r"(보안\s*(리포트|결과)|report)"},
    {"label": "전자정부프레임워크 가이드", "url": "/support/guide/egovframework", "pat": r"(전자정부|e[-_ ]?gov|egov).*가이드"},
    {"label": "자료실", "url": "/support/download", "pat": r"(자료실|자료|다운로드)"},
    {"label": "알림마당", "url": "/inform", "pat": r"(알림|inform)"},
]

def _suggest_actions_from_text(text: str, limit: int = 3) -> List[Dict[str, str]]:
    text_norm = (text or "").lower()
    hits = []
    for r in ROUTES:
        if re.search(r["pat"], text_norm, flags=re.I):
            hits.append({"label": r["label"], "url": r["url"]})
    if not hits:
        if ("보안" in text) or re.search(r"\bsecurity\b", text_norm):
            hits.append({"label": "AI 보안 검사", "url": "/support/security/scan"})
        if ("변환" in text) or re.search(r"\btransform|convert\b", text_norm):
            hits.append({"label": "변환 하기", "url": "/support/transform/transformation"})
        if ("가이드" in text) or ("전자정부" in text):
            hits.append({"label": "전자정부프레임워크 가이드", "url": "/support/guide/egovframework"})
    uniq, seen = [], set()
    for a in hits:
        if a["url"] in seen: 
            continue
        uniq.append(a); seen.add(a["url"])
        if len(uniq) >= limit: 
            break
    return uniq

# -------------------- RAG 인덱서 --------------------
class SimpleRAG:
    """
    기존 버전은 knowledge 디렉토리의 .txt/.md만 인덱싱했는데,
    여기에 .pdf 지원과 증분 ingest(업로드 즉시 반영)를 추가합니다.
    """
    def __init__(self, index_dir="./rag_index", knowledge_dir="./knowledge"):
        self.index_dir = index_dir
        self.knowledge_dir = knowledge_dir
        self.store = None
        self._ensure_loaded()

    # 내부 유틸: 문서 읽기
    def _read_txt_md(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fp:
                return fp.read()
        except Exception:
            return ""

    def _read_pdf(self, path: str) -> str:
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(path)
            texts = []
            for pg in reader.pages:
                t = pg.extract_text() or ""
                if t:
                    texts.append(t)
            return "\n".join(texts)
        except Exception:
            return ""

    def _walk_knowledge(self) -> List[Tuple[str, str]]:
        """
        knowledge_dir 안의 .txt/.md/.pdf 를 읽어 [(source, text)] 반환
        """
        out: List[Tuple[str, str]] = []
        if not os.path.isdir(self.knowledge_dir):
            return out
        for root, _, files in os.walk(self.knowledge_dir):
            for f in files:
                low = f.lower()
                p = os.path.join(root, f)
                text = ""
                if low.endswith((".txt", ".md")):
                    text = self._read_txt_md(p)
                elif low.endswith(".pdf"):
                    text = self._read_pdf(p)
                if text.strip():
                    out.append((f, text))
        return out

    def _ensure_loaded(self):
        if not (FAISS and OpenAIEmbeddings and OPENAI_API_KEY):
            return
        try:
            self.store = FAISS.load_local(
                self.index_dir,
                OpenAIEmbeddings(api_key=OPENAI_API_KEY),
                allow_dangerous_deserialization=True,
            )
        except Exception:
            self._rebuild_from_source()

    def _split(self, text: str):
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150) if RecursiveCharacterTextSplitter else None
        if splitter:
            return splitter.split_text(text)
        # 최악의 경우 간단 분할
        return [text[i:i+1000] for i in range(0, len(text), 1000)]

    def _rebuild_from_source(self):
        if not (FAISS and OpenAIEmbeddings and OPENAI_API_KEY):
            return
        docs, meta = [], []
        for name, content in self._walk_knowledge():
            for chunk in self._split(content):
                docs.append(chunk); meta.append({"source": name})
        if not docs:
            return
        embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
        self.store = FAISS.from_texts(docs, embeddings, metadatas=meta)
        os.makedirs(self.index_dir, exist_ok=True)
        self.store.save_local(self.index_dir)

    # 외부에서 호출: 전체 재색인
    def rebuild(self):
        self._rebuild_from_source()

    # 외부에서 호출: 파일 경로 리스트를 증분 인덱싱
    def ingest_files(self, paths: List[str]) -> int:
        if not (FAISS and OpenAIEmbeddings and OPENAI_API_KEY):
            return 0
        texts, metas = [], []
        for p in paths:
            low = p.lower()
            name = os.path.basename(p)
            if low.endswith((".txt", ".md")):
                t = self._read_txt_md(p)
            elif low.endswith(".pdf"):
                t = self._read_pdf(p)
            else:
                continue
            if not t.strip():
                continue
            for chunk in self._split(t):
                texts.append(chunk); metas.append({"source": name})
        if not texts:
            return 0
        if self.store is None:
            # 최초 빌드
            embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
            self.store = FAISS.from_texts(texts, embeddings, metadatas=metas)
        else:
            self.store.add_texts(texts, metadatas=metas)
        os.makedirs(self.index_dir, exist_ok=True)
        self.store.save_local(self.index_dir)
        return len(texts)

    def list_files(self) -> List[str]:
        out = []
        if not os.path.isdir(self.knowledge_dir):
            return out
        for root, _, files in os.walk(self.knowledge_dir):
            for f in files:
                if f.lower().endswith((".txt", ".md", ".pdf")):
                    out.append(os.path.relpath(os.path.join(root, f), self.knowledge_dir))
        return sorted(out)

    def retrieve(self, query: str, k: int = 4) -> List[Dict[str, str]]:
        if not self.store:
            return []
        results = self.store.similarity_search(query, k=k)
        return [{"source": d.metadata.get("source", "doc"), "text": d.page_content} for d in results]

RAG = SimpleRAG()

# -------------------- LLM --------------------
def _build_llm():
    if not OPENAI_API_KEY:
        return None, "no_api_key"
    if ChatOpenAI is None:
        return None, "missing_langchain_openai"
    try:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, api_key=OPENAI_API_KEY)
        return llm, "ok"
    except Exception as e:
        return None, f"init_error:{type(e).__name__}"

# -------------------- 메인 에이전트 --------------------
def call_agent(request: Dict[str, Any]) -> Dict[str, Any]:
    text = (request or {}).get("text", "")[:4000]
    actions = _suggest_actions_from_text(text)
    snippets = RAG.retrieve(text, k=4)

    llm, reason = _build_llm()
    if llm:
        context = "\n\n".join([f"[{i+1}] {s['text']}" for i, s in enumerate(snippets)])
        sys = ("당신은 eGovFrame 기반 사이트의 AI 도우미입니다. 한국어로 간결하고 실용적으로 답하세요. "
               "제공된 컨텍스트를 우선 활용하되, 모르면 솔직히 모른다고 하세요.")
        prompt = (
            f"사용자 질문: {text}\n\n"
            f"컨텍스트:\n{context if context else '(없음)'}\n\n"
            f"요청: 1~2문단으로 답하고, 사용자가 바로 이동할 수 있게 내부 기능을 1~3개 추천하세요."
        )
        messages = [{"role": "system", "content": sys}, {"role": "user", "content": prompt}]
        try:
            resp = llm.invoke(messages)
            reply = getattr(resp, "content", None) or (resp if isinstance(resp, "str") else "")
        except Exception as e:
            reply = "요청을 이해했어요. 관련 기능으로 이동할 수 있는 버튼을 아래에 제안드릴게요."
            reason = f"invoke_error:{type(e).__name__}"
    else:
        reply = ("요청을 이해했어요. OpenAI 키가 설정되면 더 자세히 답변할 수 있어요. "
                 "지금은 관련 기능 경로를 버튼으로 안내드릴게요.")

    citations = [{"source": s["source"], "snippet": s["text"][:180]} for s in snippets]
    return {
        "reply": reply.strip(),
        "actions": actions,
        "citations": citations,
        "meta": {"model": "gpt-4o-mini" if llm else "rule-fallback", "has_rag": bool(snippets), "reason": reason},
    }
