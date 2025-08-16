# rag_security_agent.py
import os
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

# === deps ===
from time import perf_counter
import numpy as np
from sentence_transformers import SentenceTransformer
from openai import OpenAI

import chromadb
from chromadb.config import Settings

# (선택) LLM 에이전트로 JSON을 문장화/보정하고 싶을 때 사용
from crewai import Agent, Task, Crew, LLM

# =========================
# 설정
# =========================
BASE = Path(__file__).resolve().parent
AGENT_INPUTS_PATH = BASE / "outputs" / "agent_inputs.json"
OUTPUT_DIR = BASE / "outputs" / "security_reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LIMIT_ISSUES = 5


# --- timeouts & skips ---
RAG_SKIP_TEXT = os.getenv("RAG_SKIP_TEXT", "0") == "1"
RAG_SKIP_CODE = os.getenv("RAG_SKIP_CODE", "0") == "1"
CHROMA_QUERY_TIMEOUT = float(os.getenv("CHROMA_QUERY_TIMEOUT", "15"))  # seconds


# Chroma 폴더(폴더 전체가 DB)
CHROMA_PERSIST_DIR = str(BASE)                         # 필요 시 ./chroma 등으로 변경
TEXT_COLLECTION_NAME = "security_text_e5l"            # 인덱싱 때 사용한 텍스트 컬렉션명
CODE_COLLECTION_NAME = "security_code_oai3l"          # 인덱싱 때 사용한 코드 컬렉션명

# OpenAI
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
OPENAI_EMBED_MODEL = "text-embedding-3-large"
OPENAI_EMBED_DIM: Optional[int] = None   # 인덱싱 때 dimensions를 썼다면 동일 수치(예: 1024)

# =========================
# 유틸
# =========================
def load_agent_inputs(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else [data]

EXT2LANG = {
    ".py":"python",".java":"java",".js":"javascript",".ts":"typescript",
    ".cs":"csharp",".cpp":"cpp",".c":"c",".go":"go",".rb":"ruby",".php":"php",
    ".kt":"kotlin",".rs":"rust"
}
def detect_lang(issue: Dict[str, Any]) -> Optional[str]:
    # 1) rule 프리픽스에서 추정 (예: python:S1481)
    rule = (issue.get("rule") or "")
    if ":" in rule:
        lang = rule.split(":",1)[0].strip().lower()
        if lang: return lang
    # 2) 파일 확장자에서 추정
    comp = issue.get("component") or ""
    return EXT2LANG.get(Path(comp).suffix.lower())

def sanitize_filename(name: str) -> str:
    return name.replace("/", "_").replace("\\", "_").strip()

# =========================
# 임베더 (쿼리 전용)
# =========================
_e5_query = SentenceTransformer("intfloat/multilingual-e5-large")

def embed_e5_query(q: str) -> List[float]:
    v = _e5_query.encode([f"query: {q}"], normalize_embeddings=True)[0]
    return v.tolist()

def embed_openai_query(q: str) -> List[float]:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.embeddings.create(model=OPENAI_EMBED_MODEL, input=[q], dimensions=OPENAI_EMBED_DIM)
    vec = np.array(resp.data[0].embedding, dtype=np.float32)
    vec = vec / (np.linalg.norm(vec) + 1e-12)  # L2
    return vec.tolist()

# =========================
# Chroma 연결
# =========================
def init_chroma(persist_dir: str):
    return chromadb.PersistentClient(path=persist_dir, settings=Settings(anonymized_telemetry=False))

def get_text_code_collections(client):
    # 이름으로 가져오되, 실패 시 목록 노출
    try:
        print("  → get text collection ...")
        text_col = client.get_collection(TEXT_COLLECTION_NAME)
        print("    ✓ text collection ok")
    except Exception as e:
        names = [c.name for c in client.list_collections()]
        raise RuntimeError(f"텍스트 컬렉션 '{TEXT_COLLECTION_NAME}' 없음. 실제 목록: {names}") from e
    try:
        print("  → get code collection ...")
        code_col = client.get_collection(CODE_COLLECTION_NAME)
        print("    ✓ code collection ok")
    except Exception as e:
        names = [c.name for c in client.list_collections()]
        raise RuntimeError(f"코드 컬렉션 '{CODE_COLLECTION_NAME}' 없음. 실제 목록: {names}") from e
    return text_col, code_col

# =========================
# 검색 & 융합 (RRF)
# =========================
def rrf(ids_a: List[str], ids_b: List[str], k=60, w_a=0.6, w_b=0.4) -> List[str]:
    score={}
    for r,i in enumerate(ids_a,1): score[i]=score.get(i,0)+w_a*(1/(k+r))
    for r,i in enumerate(ids_b,1): score[i]=score.get(i,0)+w_b*(1/(k+r))
    return sorted(score, key=score.get, reverse=True)

def query_collection(col, qvec, topk=5, where=None):
    return col.query(
        query_embeddings=[qvec],
        n_results=topk,
        include=["documents","metadatas","distances"],
        where=where
    )

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
def query_collection_safe(col, qvec, topk=5, where=None, label="TEXT"):
    """
    Windows 안전 버전: 스레드/타임아웃 미사용.
    - RAG_FORCE_PEEK=1 이면 query 생략하고 peek()만 사용
    - query가 Python 레벨에서 예외를 던지면 peek()로 폴백
    """
    try:
        if os.getenv("RAG_FORCE_PEEK", "0") == "1":
            print(f"   {label} forced peek (RAG_FORCE_PEEK=1)")
            pk = col.peek()
            docs = (pk.get("documents") or [])
            docs = docs[:topk] if isinstance(docs, list) else []
            return {
                "ids": [[f"__peek__{i}" for i in range(len(docs))]],
                "documents": [docs],
                "metadatas": [[]],
                "distances": [[]],
            }

        # 동기 호출(스레드X). include 최소화로 지연 줄이기
        return col.query(
            query_embeddings=[qvec],
            n_results=topk,
            include=["documents"],     # 최소
            where=where
        )

    except Exception as e:
        print(f"   {label} query raised: {e} → fallback to peek()")
        try:
            pk = col.peek()
            docs = (pk.get("documents") or [])
            docs = docs[:topk] if isinstance(docs, list) else []
            return {
                "ids": [[f"__peek__{i}" for i in range(len(docs))]],
                "documents": [docs],
                "metadatas": [[]],
                "distances": [[]],
            }
        except Exception as e2:
            print(f"   {label} peek failed: {e2}")
            return {"ids":[[]], "documents":[[]], "metadatas":[[]], "distances":[[]]}

def retrieve_context_dual(text_col, code_col, query: str, lang: Optional[str], k: int = 5) -> List[str]:
    # 1) TEXT(E5)
    if RAG_SKIP_TEXT:
        print("   TEXT search skipped (RAG_SKIP_TEXT=1)")
        res_t = {"ids":[[]], "documents":[[]], "metadatas":[[]], "distances":[[]]}
    else:
        t0 = perf_counter()
        qv_text = embed_e5_query(query)
        print("   [TEXT] querying ...")
        res_t = query_collection_safe(text_col, qvec=qv_text, topk=k, where=None, label="TEXT")
        ids_t = (res_t.get("ids") or [[]])[0]
        docs_t = (res_t.get("documents") or [[]])[0]
        print(f"   TEXT hits={len(ids_t)} ({perf_counter()-t0:.2f}s)")

    # 2) CODE(OpenAI) — 언어필터 우선, 0이면 필터 해제 재시도
    if RAG_SKIP_CODE:
        print("   CODE search skipped (RAG_SKIP_CODE=1)")
        res_c = {"ids":[[]], "documents":[[]], "metadatas":[[]], "distances":[[]]}
    else:
        t1 = perf_counter()
        qv_code = embed_openai_query(query)
        where = {"code_lang": lang} if lang else None
        print(f"   [CODE] querying ... (filter={where})")
        res_c = query_collection_safe(code_col, qvec=qv_code, topk=k, where=where, label="CODE")
        ids_c = (res_c.get("ids") or [[]])[0]
        docs_c = (res_c.get("documents") or [[]])[0]
        if not ids_c and where is not None:
            print("   [CODE] 0 hits with filter → retry without filter")
            res_c = query_collection_safe(code_col, qvec=qv_code, topk=k, where=None, label="CODE")
            ids_c = (res_c.get("ids") or [[]])[0]
            docs_c = (res_c.get("documents") or [[]])[0]
        print(f"   CODE hits={len(ids_c)} ({perf_counter()-t1:.2f}s)")

    # 3) RRF 융합 (기존 로직 그대로)
    ids_t = (res_t.get("ids") or [[]])[0]
    docs_t = (res_t.get("documents") or [[]])[0]
    ids_c = (res_c.get("ids") or [[]])[0]
    docs_c = (res_c.get("documents") or [[]])[0]

    fused_ids = rrf(ids_t, ids_c, k=60, w_a=0.6, w_b=0.4)
    pool = {i:d for i,d in zip(ids_t, docs_t)}
    for i,d in zip(ids_c, docs_c):
        pool.setdefault(i,d)
    docs_out = [pool[i] for i in fused_ids[:k] if i in pool]
    print(f"   FUSED topk={len(docs_out)}")
    return docs_out

# =========================
# 질의 문자열
# =========================
def build_query(issue: Dict[str, Any]) -> str:
    msg = (issue.get("message") or "").strip()
    tags = " ".join([str(t) for t in (issue.get("tags") or []) if t])
    rule = (issue.get("rule") or "").strip()
    base = " ".join([msg, tags, rule]).strip()
    # 보안 가이드 회수 향상을 위한 힌트(한국어 키워드)
    return f"{base} 보안 가이드 개선 방법 취약점 원인 해결책 모범사례 코드예시".strip()

# =========================
# LLM (CrewAI) - JSON 작성
# =========================
def make_system_prompt() -> str:
    return (
        "당신은 전자정부프레임워크 보안개발가이드에 정통한 보안 감사 에이전트입니다. "
        "입력 이슈(SonarQube)와 검색 문맥을 바탕으로, 다음 JSON 스키마에 정확히 맞게 응답하세요. "
        "설명 문장이나 코드블록 표시는 금지합니다."
    )

def make_task_description(issue: Dict[str, Any], docs: List[str]) -> str:
    ctx = "\n\n".join([f"- {d}" for d in docs])
    return f"""
[이슈]
- rule: {issue.get('rule')}
- severity: {issue.get('severity')}
- component: {issue.get('component')}
- line: {issue.get('line')}
- message: {issue.get('message')}
- tags: {', '.join(issue.get('tags') or [])}

[검색 문맥(상위 {len(docs)}개)]
{ctx}

[JSON 스키마]
{{
  "rule": "...",
  "severity": "...",
  "component": "...",
  "line": "...",
  "risk_level": "Critical|High|Medium|Low",
  "root_cause": "...",
  "impact": "...",
  "fix_guidance": [
    "구체적 조치 1",
    "구체적 조치 2"
  ],
  "secure_code_example": "가능하면 짧은 코드 스니펫",
  "checklist": [
    "점검 항목 1",
    "점검 항목 2"
  ],
  "references": [
    "가이드/규정 페이지 또는 키워드",
    "관련 규칙(rule) 참고"
  ]
}}
""".strip()

def parse_llm_json(txt: str, issue: Dict[str, Any]) -> Dict[str, Any]:
    s = str(txt).strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()
    try:
        data = json.loads(s)
    except Exception:
        # 최소 폴백
        data = {
            "rule": issue.get("rule"),
            "severity": issue.get("severity"),
            "component": issue.get("component"),
            "line": issue.get("line"),
            "root_cause": issue.get("message"),
            "fix_guidance": [issue.get("message")],
            "checklist": [],
            "references": []
        }
    # 스키마 누락 필드 보정
    data.setdefault("risk_level", "Low")
    data.setdefault("impact", "")
    data.setdefault("secure_code_example", "")
    data.setdefault("fix_guidance", [])
    data.setdefault("checklist", [])
    data.setdefault("references", [])
    return data

# =========================
# 메인
# =========================
def main():
    # 0) 입력
    issues = load_agent_inputs(AGENT_INPUTS_PATH)
    if LIMIT_ISSUES:
        issues = issues[:LIMIT_ISSUES]
    print(f"🗂 issues: {len(issues)} | inputs: {AGENT_INPUTS_PATH.resolve()}")

    # 1) Chroma
    print(f"🔌 opening Chroma at: {CHROMA_PERSIST_DIR}")
    client = init_chroma(CHROMA_PERSIST_DIR)
    print("🔍 listing collections...")
    names = [c.name for c in client.list_collections()]
    print("📚 collections found:", names)

    print(f"📦 getting collections: text='{TEXT_COLLECTION_NAME}', code='{CODE_COLLECTION_NAME}'")
    text_col, code_col = get_text_code_collections(client)
    print("✅ collections fetched. (skip counting to avoid blocking)")

    # 2) LLM 준비 (CrewAI)
    llm = LLM(
        model=OPENAI_CHAT_MODEL,
        temperature=0.2,
        api_key=os.getenv("OPENAI_API_KEY"),
    )
    security_agent = Agent(
        role="Security Auditor",
        goal="RAG 문맥을 근거로 Sonar 이슈의 보안 리스크와 구체적 개선 가이드를 산출",
        backstory="전자정부프레임워크 보안개발 가이드에 정통. 실무형 조언 제공에 특화.",
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=1,
        system_prompt=make_system_prompt(),
    )

    # 3) 이슈별 처리
    all_rows = []
    summary_rows = []
    for idx, issue in enumerate(issues, start=1):
        q = build_query(issue)
        lang = detect_lang(issue)
        print(f"[{idx}/{len(issues)}] {issue.get('component')}:{issue.get('line')} rule={issue.get('rule')} | lang={lang}")
        docs = retrieve_context_dual(text_col, code_col, q, lang=lang, k=5)

        task = Task(
            description=make_task_description(issue, docs),
            agent=security_agent,
            expected_output="위 스키마에 맞는 단일 JSON 문자열"
        )
        crew = Crew(agents=[security_agent], tasks=[task], verbose=False)
        out = crew.kickoff()

        data = parse_llm_json(str(out), issue)
        data["_issue"] = issue  # 원본 보존

        # 이슈별 JSON 저장
        fname = f"{sanitize_filename(issue.get('component') or 'issue')}__{issue.get('line','0')}.json"
        (OUTPUT_DIR / fname).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  → saved {fname}")

        all_rows.append(data)
        summary_rows.append({
            "component": issue.get("component"),
            "line": issue.get("line"),
            "rule": issue.get("rule"),
            "output_file": fname
        })

    # 4) 전체 JSONL & summary.json
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = OUTPUT_DIR / f"security_reports_{ts}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ done: {len(all_rows)} items")
    print(f"   - {jsonl_path}")
    print(f"   - {OUTPUT_DIR / 'summary.json'}")

if __name__ == "__main__":
    main()
