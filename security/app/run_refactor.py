# run_refactor.py — LangGraph + FAISS(dual-embedding) 파이프라인
# 입력: outputs/agent_inputs.json
# 벡터스토어: index/faiss_text_lc/, index/faiss_code_lc/ (LangChain FAISS 포맷)
# 출력: outputs/security_reports/*.md, outputs/security_reports/report.json

import os, re, json, time, argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

import numpy as np
from openai import OpenAI
from langgraph.graph import StateGraph, END

from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from sentence_transformers import SentenceTransformer

# LangSmith & LangChain-OpenAI
from langsmith.run_helpers import traceable
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage


# # 상단 import에 추가
# import subprocess
# from sonar_api import wait_for_ce_success, collect_and_write_agent_inputs, SONAR_URL, PROJECT_KEY

# # argparse 옵션 추가
# ap.add_argument("--scan", action="store_true", help="사전 Sonar 스캔+수집 자동 수행")
# ap.add_argument("--project-path", default=None, help="sonar-scanner를 실행할 프로젝트 루트")
# ap.add_argument("--scanner-bin", default="sonar-scanner", help="sonar-scanner 실행 파일명")


# ---------------- paths & constants ----------------
BASE = Path(__file__).resolve().parent
INDEX_DIR = BASE / "index"
TEXT_STORE_DIR = INDEX_DIR / "faiss_text_lc"
CODE_STORE_DIR = INDEX_DIR / "faiss_code_lc"
OUT_DIR = BASE / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
AGENT_INPUTS = OUT_DIR / "agent_inputs.json"
REPORT_DIR = OUT_DIR / "security_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

TEXT_EMBED_MODEL = os.getenv("TEXT_EMBED_MODEL", "intfloat/multilingual-e5-large")
CODE_EMBED_MODEL = os.getenv("CODE_EMBED_MODEL", "text-embedding-3-large")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")

TOP_K_DEFAULT = int(os.getenv("TOP_K", "8"))
W_TEXT_DEFAULT = float(os.getenv("W_TEXT", "0.6"))
W_CODE_DEFAULT = float(os.getenv("W_CODE", "0.4"))

# ---------------- helpers (filename/query) ----------------

def strip_md_link(s: str) -> str:
    if not s: return s
    m = re.match(r"\[([^\]]+)\]\([^)]+\)", s)
    return m.group(1) if m else s

def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", name or "unknown")

def slugify(s: str, max_len: int = 40) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^0-9a-z]+", "-", s).strip("-")
    return s[:max_len] or "na"

def make_filename(issue: Dict[str, Any], idx: int) -> str:
    comp_raw  = strip_md_link(issue.get("component", "unknown"))
    comp_base = Path(comp_raw).name
    comp_base = re.sub(r"\.[^.]+$", "", comp_base)
    comp_slug = slugify(comp_base, 40)
    rule_slug = slugify(issue.get("rule", ""), 40)
    try:
        line_int = int(issue.get("line", 0) or 0)
    except Exception:
        line_int = 0
    return safe_filename(f"{comp_slug}-L{line_int:04d}-R{rule_slug}-N{idx:02d}.md")

def build_issue_query_string(issue: Dict[str, Any]) -> str:
    parts=[]
    if issue.get("search_query"): parts.append(issue["search_query"])
    if issue.get("message"): parts.append(issue["message"])
    if issue.get("rule"): parts.append(issue["rule"])
    if issue.get("tags"): parts.append(" ".join(issue["tags"]))
    comp = strip_md_link(issue.get("component",""))
    if comp: parts.append(comp)
    if issue.get("line"): parts.append(f"line {issue['line']}")
    return " | ".join([p for p in parts if p]).strip()

# ---------------- embeddings (LangChain-compatible) ----------------
class E5EmbeddingsLC(Embeddings):
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
    def __init__(self, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.client = OpenAI(api_key=api_key, base_url=base_url) if (api_key or base_url) else OpenAI()
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

# ---------------- load vector stores ----------------
VS_TEXT = None
VS_CODE = None

def load_vectorstores() -> None:
    global VS_TEXT, VS_CODE
    txt_emb = E5EmbeddingsLC(TEXT_EMBED_MODEL)
    cod_emb = OpenAIEmbeddingsLC(CODE_EMBED_MODEL)
    VS_TEXT = FAISS.load_local(str(TEXT_STORE_DIR), embeddings=txt_emb, allow_dangerous_deserialization=True)
    VS_CODE = FAISS.load_local(str(CODE_STORE_DIR), embeddings=cod_emb, allow_dangerous_deserialization=True)

# ---------------- LangGraph state ----------------
class State(TypedDict, total=False):
    issue: Dict[str, Any]
    idx: int
    topk: int
    weight_text: float
    weight_code: float
    message: str
    queries: List[str]
    hits_text: List[List[Document]]
    hits_code: List[List[Document]]
    fused_docs: List[Document]
    sampled_docs: List[Document]
    guide_markdown: str
    guide_title: str

# ---------------- nodes ----------------
@traceable(name="build_query")
def node_build_query(state: State) -> State:
    msg = build_issue_query_string(state["issue"])  # base
    tags = " ".join(state["issue"].get("tags", []))
    rule = state["issue"].get("rule", "")
    q1 = msg
    q2 = f"{msg} 코드 예시 안전/취약 비교 보안대책"
    q3 = f"{msg} 태그:{tags} 규정:{rule} 개요 대책 참고"
    state["message"] = msg
    state["queries"] = [q1, q2, q3]
    return state

@traceable(name="retrieve_dual")
def node_retrieve_dual(state: State) -> State:
    assert VS_TEXT is not None and VS_CODE is not None, "VectorStores not loaded"
    topk = state.get("topk", TOP_K_DEFAULT)
    hits_text: List[List[Document]] = []
    hits_code: List[List[Document]] = []
    for q in state["queries"]:
        hits_text.append(VS_TEXT.similarity_search(q, k=topk))
        hits_code.append(VS_CODE.similarity_search(q, k=topk))
    state["hits_text"] = hits_text
    state["hits_code"] = hits_code
    return state

# weighted RRF for Document lists
def rrf_weighted(lists: List[List[Document]], weights: List[float], k:int=60) -> List[Document]:
    score: Dict[str, float] = {}
    keep: Dict[str, Document] = {}
    for L, w in zip(lists, weights):
        for rank, d in enumerate(L):
            doc_id = d.metadata.get("doc_id") or f"{d.metadata.get('security_id')}#{d.metadata.get('section')}"
            score[doc_id] = score.get(doc_id, 0.0) + w * (1.0/(k+rank+1))
            if doc_id not in keep:
                keep[doc_id] = d
    fused = sorted([(doc_id, sc) for doc_id, sc in score.items()], key=lambda x: x[1], reverse=True)
    return [keep[doc_id] for doc_id,_ in fused]


@traceable(name="fuse_rrf")
def node_fuse_rrf(state: State) -> State:
    text_all = [h for L in state["hits_text"] for h in L]
    code_all = [h for L in state["hits_code"] for h in L]
    w_t = state.get("weight_text", W_TEXT_DEFAULT)
    w_c = state.get("weight_code", W_CODE_DEFAULT)
    fused = rrf_weighted([text_all, code_all], [w_t, w_c], k=60)
    state["fused_docs"] = fused[: state.get("topk", TOP_K_DEFAULT)]
    return state

SECTIONS = ["overview","mitigation","unsafe_examples","safe_examples","references"]

@traceable(name="section_coverage")
def node_section_coverage(state: State) -> State:
    by_sec: Dict[str, List[Document]] = {s: [] for s in SECTIONS}
    for d in state["fused_docs"]:
        s = d.metadata.get("section", "")
        if s in by_sec:
            by_sec[s].append(d)
    picked: List[Document] = []
    for s in SECTIONS:
        if by_sec[s]:
            picked.append(by_sec[s][0])
    # fill up to topk
    if len(picked) < state.get("topk", TOP_K_DEFAULT):
        seen = {id(x) for x in picked}
        for d in state["fused_docs"]:
            if len(picked) >= state.get("topk", TOP_K_DEFAULT):
                break
            if id(d) in seen: continue
            picked.append(d); seen.add(id(d))
    state["sampled_docs"] = picked
    return state

SYSTEM_PROMPT = (
    "You are a senior application security engineer. Respond in Korean unless code.\n"
    "형식: 개요 → 대책 체크리스트 → (취약→안전) 코드 예시 → 참고자료"
)

def render_snippets(docs: List[Document]) -> str:
    out=[]
    for i, d in enumerate(docs, 1):
        m=d.metadata; txt=d.page_content[:600]
        out.append(f"[{i}] {m.get('security_name')} / {m.get('section')}\n{txt}")
    return "\n\n".join(out) if out else "(검색 컨텍스트 없음)"

@traceable(name="generate_guide")
def node_generate_guide(state: State) -> State:
    # client = OpenAI()
    issue = state["issue"]
    docs = state.get("sampled_docs", [])
    snippets = render_snippets(docs)
    title = docs[0].metadata.get("security_name") if docs else "보안 가이드"

    comp = strip_md_link(issue.get("component", ""))
    rule = issue.get("rule", "")
    severity = issue.get("severity", "")
    line = issue.get("line", "")
    message = issue.get("message", "")
    tags = ", ".join(issue.get("tags", []))

    user_prompt = (
        "다음 이슈에 대한 보안 가이드를 작성하세요.\n\n"
        "[이슈]\n"
        f"- 규칙: {rule}\n- 중요도: {severity}\n- 파일: {comp} (line {line})\n- 메시지: {message}\n- 태그: {tags}\n\n"
        "[검색 컨텍스트]\n" + snippets + "\n\n"
        f"# {title}\n"
        "## 개요\n"
        "## 보안 대책 체크리스트\n"
        "## 코드 예시 (취약 → 안전)\n"
        "## 참고자료\n"
    )

    # resp = client.chat.completions.create(
    #     model=CHAT_MODEL,
    #     messages=[{"role":"system","content": SYSTEM_PROMPT},{"role":"user","content": user_prompt}],
    #     temperature=0.2,
    # )
    llm = ChatOpenAI(model=CHAT_MODEL, temperature=0.2)
    resp = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ])
    md = resp.content.strip()
    state["guide_markdown"] = md
    state["guide_title"] = title
    return state

@traceable(name="emit_artifacts")
def node_emit_artifacts(state: State) -> State:
    idx = state["idx"]
    issue = state["issue"]
    md = state.get("guide_markdown", "# 보안 가이드")
    fname = make_filename(issue, idx)
    (REPORT_DIR / fname).write_text(md, encoding="utf-8")
    # side log file will be written by the driver after invoke
    print(f"✓ [{idx}] -> {fname}")
    return state

# ---------------- build graph ----------------

def build_graph():
    g = StateGraph(State)
    g.add_node("build_query", node_build_query)
    g.add_node("retrieve_dual", node_retrieve_dual)
    g.add_node("fuse_rrf", node_fuse_rrf)
    g.add_node("section_coverage", node_section_coverage)
    g.add_node("generate_guide", node_generate_guide)
    g.add_node("emit_artifacts", node_emit_artifacts)

    g.set_entry_point("build_query")
    g.add_edge("build_query", "retrieve_dual")
    g.add_edge("retrieve_dual", "fuse_rrf")
    g.add_edge("fuse_rrf", "section_coverage")
    g.add_edge("section_coverage", "generate_guide")
    g.add_edge("generate_guide", "emit_artifacts")
    g.add_edge("emit_artifacts", END)
    return g.compile()

# ---------------- driver ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langsmith", action="store_true", help="LangSmith tracing 활성화")
    ap.add_argument("--ls-project", default=os.getenv("LANGSMITH_PROJECT", "security-refactor"))
    ap.add_argument("--ls-endpoint", default=os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"))
    ap.add_argument("--ls-api-key", default=os.getenv("LANGSMITH_API_KEY"))
    ap.add_argument("--topk", type=int, default=TOP_K_DEFAULT)
    ap.add_argument("--w-text", type=float, default=W_TEXT_DEFAULT)
    ap.add_argument("--w-code", type=float, default=W_CODE_DEFAULT)
    args = ap.parse_args()

    # LangSmith enable/disable
    if args.langsmith or os.getenv("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes", "on"):
        if args.ls_api_key:
            os.environ.setdefault("LANGSMITH_API_KEY", args.ls_api_key)
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGSMITH_ENDPOINT", args.ls_endpoint)
        os.environ.setdefault("LANGSMITH_PROJECT", args.ls_project)
    else:
        os.environ.setdefault("LANGSMITH_TRACING", "false")



    # load vector stores once
    load_vectorstores()

    # load issues
    issues = json.loads(AGENT_INPUTS.read_text(encoding="utf-8"))
    assert isinstance(issues, list)

    graph = build_graph()

    report: List[Dict[str, Any]] = []
    for i, issue in enumerate(issues[:5], 1):
        state: State = {
            "issue": issue,
            "idx": i,
            "topk": args.topk,
            "weight_text": args.w_text,
            "weight_code": args.w_code,
        }
        # out = graph.invoke(state)
        invoke_cfg = {
            "run_name": f"issue-{i}-{issue.get('rule','')}",
            "tags": ["security_agent", "run_refactor", issue.get("severity","")],
            "metadata": {
                "component": strip_md_link(issue.get("component","")),
                "line": issue.get("line"),
                "rule": issue.get("rule"),
                "severity": issue.get("severity"),
                "topk": args.topk,
                "w_text": args.w_text,
                "w_code": args.w_code,
            },
        }
        out = graph.invoke(state, config=invoke_cfg)


        report.append({
            "issue_index": i,
            "rule": issue.get("rule"),
            "component": strip_md_link(issue.get("component","")),
            "line": issue.get("line"),
            "severity": issue.get("severity"),
            "tags": issue.get("tags", []),
            "search_query": issue.get("search_query"),
            "guide_file": str((REPORT_DIR / make_filename(issue, i)).relative_to(BASE)),
            "guide_title": out.get("guide_title", "보안 가이드"),
        })

    (REPORT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("✅ 전체 리포트 저장:", REPORT_DIR / "report.json")

if __name__ == "__main__":
    main()
