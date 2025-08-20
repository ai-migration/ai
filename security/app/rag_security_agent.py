# rag_security_agent.py
import os
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

# --- Chroma & CrewAI / OpenAI ---
import chromadb
from chromadb.config import Settings
from crewai import Agent, Task, Crew, LLM
# CrewAI 0.51+ 기준. 하위 버전이면 llm 지정 방식/파라미터 조금 다를 수 있음.
# 설치: pip install crewai chromadb openai tiktoken

import numpy as np
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from time import perf_counter


# ====== 설정 ======
BASE = Path(__file__).resolve().parent
AGENT_INPUTS_PATH = BASE / "outputs" / "agent_inputs.json"
OUTPUT_DIR = BASE / "outputs" / "security_reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LIMIT_ISSUES = 5

# 업로드한 chroma.sqlite3가 현재 폴더에 있다고 가정 (경로 바꿔도 됨)
CHROMA_PERSIST_DIR = str(Path(".").resolve())           # sqlite 파일이 있는 폴더 경로
CHROMA_DB_FILE = Path("chroma.sqlite3")                 # sqlite 파일명
# 컬렉션 이름 모르면 자동으로 첫 컬렉션 사용 시도
DEFAULT_COLLECTION_NAME = None                          # 예: "security_guide" 로 지정 가능

OPENAI_MODEL = "gpt-4o-mini"  # 비용/속도 균형용. 필요시 상위 모델로.

# ====== 헬퍼 ======

COLLECTION_KIND = {
    "security_code_oai3l": "code",  # OpenAI text-embedding-3-large로 색인한 컬렉션
    "security_text_e5l": "text",     # E5(multilingual-e5-large)로 색인한 컬렉션
}

class E5QueryEmbedder:
    def __init__(self, model_name="intfloat/multilingual-e5-large"):
        self.model = SentenceTransformer(model_name)
    def embed(self, query: str):
        vec = self.model.encode([f"query: {query}"], normalize_embeddings=True)
        return vec[0].tolist()

class OpenAIEmbedder:
    def __init__(self, model="text-embedding-3-large", api_key=None, dimensions=None):
        self.model = model
        self.dimensions = dimensions
        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()
    def embed(self, text: str):
        resp = self.client.embeddings.create(model=self.model, input=[text], dimensions=self.dimensions)
        arr = np.array([e.embedding for e in resp.data], dtype=np.float32)
        nrm = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12
        return (arr / nrm)[0].tolist()

def load_agent_inputs(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"agent_inputs.json이 없습니다: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def init_chroma_client(persist_dir: str) -> chromadb.ClientAPI:
    # sqlite 파일이 동일 폴더에 있고, PersistentClient가 폴더 단위로 관리함
    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False)
    )
    return client


# 듀얼 RAG(코드/텍스트 컬렉션 동시 검색) + 병합
def get_collection(client, name: str | None):
    if name:
        return client.get_collection(name=name)  # ❗ embedding_function 제거
    cols = client.list_collections()
    if not cols:
        raise RuntimeError("Chroma에 컬렉션이 없습니다.")
    return client.get_collection(name=cols[0].name)  # ❗ 동일

def build_query(issue: Dict[str, Any]) -> str:
    # message + tags + rule을 묶어 검색 질의 생성
    msg = (issue.get("message") or "").strip()
    tags = issue.get("tags") or []
    rule = (issue.get("rule") or "").strip()
    tag_str = " ".join([str(t) for t in tags if t])
    # 보안 가이드 검색에 도움이 되도록 키워드 보강
    base = f"{msg} {tag_str} {rule}".strip()
    return f"{base} 보안 가이드 개선 방법 취약점 원인 해결책 모범사례 코드예시".strip()

def retrieve_context(collection, query: str, k: int = 5) -> List[str]:
    name = collection.name
    kind = COLLECTION_KIND.get(name, "text")  # 기본 텍스트로

    try: 
        # [LOG] 어떤 임베딩으로 쿼리하는지
        t0 = perf_counter()
        if kind == "code":
            print("🔎 query embedder: OpenAI text-embedding-3-large")
            emb = OpenAIEmbedder(model="text-embedding-3-large",
                                api_key=os.getenv("OPENAI_API_KEY")).embed(query)
            print(f"   ✓ embedding ok ({perf_counter()-t0:.2f}s)")
        else:
            print("🔎 query embedder: E5 multilingual-e5-large (query: prefix)")
            emb = E5QueryEmbedder("intfloat/multilingual-e5-large").embed(query)
            print(f"   ✓ embedding ok ({perf_counter()-t0:.2f}s)")
    except Exception as e:
        print(f"❌ embedding error: {e}")
        return []

    try:
        print("   → chroma.query ...")
        t1 = perf_counter()
        res = collection.query(
            query_embeddings=[emb],
            n_results=k,
            include=["documents","distances","ids","metadatas"]
        )
        docs = res.get("documents", [[]])[0]
        print(f"   ↳ retrieved docs: {len(docs)} ({perf_counter()-t1:.2f}s)")
        return docs
    except Exception as e:
        print(f"❌ chroma query error: {e}")
        return []


def make_system_prompt() -> str:
    return (
        "당신은 전자정부프레임워크 보안개발가이드에 정통한 보안 감사 에이전트입니다. "
        "입력 이슈(SonarQube)와 RAG로 검색된 가이드를 바탕으로, 보안 위험도 평가와 개선 가이드를 "
        "정확하고 실행 가능하게 작성하세요. 가능하면 간단한 코드 수정 예도 포함하세요. "
        "출력은 반드시 JSON 스키마를 준수하세요."
    )

def make_task_description(issue: Dict[str, Any], docs: List[str]) -> str:
    # 이슈 및 검색 문맥을 태스크에 주입
    ctx = "\n\n".join([f"- {d}" for d in docs])
    return f"""
[이슈]
- rule: {issue.get('rule')}
- severity: {issue.get('severity')}
- component: {issue.get('component')}
- line: {issue.get('line')}
- message: {issue.get('message')}
- tags: {', '.join(issue.get('tags') or [])}

[검색 문맥(보안 가이드 발췌, 상위 {len(docs)}개)]
{ctx}

[요구사항]
아래 JSON 스키마로만 답변하세요. 설명 문장 추가 금지.

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
    "구체적 조치 2",
    "..."
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

def save_jsonl(rows: List[Dict[str, Any]], path: Path):
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def write_markdown(issue: Dict[str, Any], result: Dict[str, Any], out_dir: Path):
    fn = f"{issue.get('component','unknown').replace('/','_')}_{issue.get('line','-')}.md"
    p = out_dir / fn
    md = [
        f"# 보안 개선 가이드: {issue.get('component')}:{issue.get('line')}",
        f"- Rule: `{result.get('rule','')}`",
        f"- Severity: `{result.get('severity','')}`",
        f"- Risk: `{result.get('risk_level','')}`",
        "",
        "## 원인(Root Cause)",
        result.get("root_cause",""),
        "",
        "## 영향(Impact)",
        result.get("impact",""),
        "",
        "## 개선 가이드",
        *[f"- {s}" for s in result.get("fix_guidance",[])],
        "",
        "## 안전한 코드 예시",
        "```",
        (result.get("secure_code_example") or "").strip(),
        "```",
        "",
        "## 점검 체크리스트",
        *[f"- [ ] {c}" for c in result.get("checklist",[])],
        "",
        "## 참고",
        *[f"- {r}" for r in result.get("references",[])]
    ]
    p.write_text("\n".join(md), encoding="utf-8")
    return p

def main():
    # 1) 입력 로드
    issues = load_agent_inputs(AGENT_INPUTS_PATH)
    # [LOG] agent_inputs 상태 확인
    print(f"🗂 loaded: {len(issues)} issues from {AGENT_INPUTS_PATH.resolve()}")
    if not issues:
        print("❌ agent_inputs가 비어있습니다. run_sonar.py → extract_agent_inputs.py 순서/경로를 확인하세요.")
        return

    # 2) Chroma 접속 & 컬렉션 선택
    if not CHROMA_DB_FILE.exists():
        print(f"⚠️ 경고: {CHROMA_DB_FILE} 가 현재 폴더에 없습니다. CHROMA_PERSIST_DIR 경로를 확인하세요.")
    client = init_chroma_client(CHROMA_PERSIST_DIR)
    collection = get_collection(client, DEFAULT_COLLECTION_NAME)
    kind = COLLECTION_KIND.get(collection.name, "text")
    print(f"✅ RAG 컬렉션 사용: {collection.name} (kind={kind})")

    # 3) CrewAI 에이전트
    chat_model = os.getenv("OPENAI_CHAT_MODEL", OPENAI_MODEL)  # 기본 gpt-4o-mini
    llm = LLM(
        model=chat_model,                    # 예: "gpt-4o-mini"  (필요시 "openai/gpt-4o-mini"로)
        temperature=0.2,
        api_key=os.getenv("OPENAI_API_KEY"), # .env 로드됨
        # base_url=os.getenv("OPENAI_BASE_URL")  # 프록시/게이트웨이 쓰면 설정
    )

    security_agent = Agent(
        role="Security Auditor",
        goal="RAG 문맥을 근거로 Sonar 이슈의 보안 리스크와 구체적 개선 가이드를 산출",
        backstory="전자정부프레임워크 보안개발 가이드에 정통. 실무형 조언 제공에 특화.",
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=1
    )



    results_jsonl = []
    issues = issues[:LIMIT_ISSUES]
    for idx, issue in enumerate(issues, start=1):
        query = build_query(issue)
        docs = retrieve_context(collection, query, k=5)

        task = Task(
            description=make_task_description(issue, docs),
            agent=security_agent,
            expected_output="위 JSON 스키마에 맞는 단일 JSON 문자열"
        )

        crew = Crew(agents=[security_agent], tasks=[task], verbose=False)
        print(f"[{idx}/{len(issues)}] 분석 중: {issue.get('component')}:{issue.get('line')} ({issue.get('rule')})")
        out = crew.kickoff()  # 문자열(JSON 형식 기대)

        # 모델 출력 JSON 파싱 보정
        txt = str(out).strip()
        # 코드블록로 감싸는 모델 습관 방지
        if txt.startswith("```"):
            txt = txt.strip("`").strip()
            # 언어태그 제거 가능
            if txt.lower().startswith("json"):
                txt = txt[4:].strip()

        try:
            data = json.loads(txt)
        except Exception:
            # 혹시 JSON이 아니면 최소 래핑
            data = {
                "rule": issue.get("rule"),
                "severity": issue.get("severity"),
                "component": issue.get("component"),
                "line": issue.get("line"),
                "raw_output": txt
            }

        # 원본 이슈 필드 부가 저장
        data["_issue"] = issue
        results_jsonl.append(data)

        # Markdown 보고서도 파일로 저장
        md_path = write_markdown(issue, data, OUTPUT_DIR)
        print(f"  → 보고서 저장: {md_path.name}")

    # 4) 전체 결과 저장
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_jsonl = OUTPUT_DIR / f"security_reports_{timestamp}.jsonl"
    save_jsonl(results_jsonl, out_jsonl)
    print(f"\n✅ 완료: {out_jsonl} (총 {len(results_jsonl)}건)")

if __name__ == "__main__":
    main()
