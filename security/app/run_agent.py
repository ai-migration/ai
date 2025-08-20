import os
import re
import json
from pathlib import Path
from typing import List, Dict, Any

from openai import OpenAI
from qdrant_client import QdrantClient

# --- Paths & settings ---
BASE = Path(__file__).resolve().parent
DB_DIR = BASE / "qdrant_local"
COLLECTION = os.getenv("COLLECTION", "security_guides_oai3")

AGENT_INPUTS = BASE / "outputs" / "agent_inputs.json"
REPORT_DIR = BASE / "outputs" / "security_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# Models
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-large")  # must match build_index.py
GEN_MODEL = os.getenv("GEN_MODEL", "gpt-4.1-mini")
TOP_K = int(os.getenv("TOP_K", "8"))


# --- Helpers ---
def strip_md_link(s: str) -> str:
    """Convert Markdown link to plain text: [label](url) -> label"""
    if not s:
        return s
    m = re.match(r"\[([^\]]+)\]\([^)]+\)", s)
    return m.group(1) if m else s


def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", name or "unknown")

# ---- consistent, sortable filenames ----
def slugify(s: str, max_len: int = 40) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^0-9a-z]+", "-", s).strip("-")
    return s[:max_len] or "na"

def make_filename(issue: Dict[str, Any], idx: int) -> str:
    # <component>-L####-R<rule>-N##.md
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



def load_issues(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list), "agent_inputs.json는 JSON 배열이어야 합니다."
    return data


def build_query(issue: Dict[str, Any]) -> str:
    parts = []
    if issue.get("search_query"):
        parts.append(issue["search_query"])
    if issue.get("message"):
        parts.append(issue["message"])
    if issue.get("rule"):
        parts.append(issue["rule"])
    if issue.get("tags"):
        parts.append(" ".join(issue["tags"]))
    comp = strip_md_link(issue.get("component", ""))
    if comp:
        parts.append(comp)
    if issue.get("line"):
        parts.append(f"line {issue['line']}")
    return " | ".join([p for p in parts if p]).strip()


def embed(client: OpenAI, text: str) -> List[float]:
    return client.embeddings.create(model=EMBED_MODEL, input=[text]).data[0].embedding


def search(qdr: QdrantClient, vec: List[float], top_k: int = TOP_K):
    return qdr.search(collection_name=COLLECTION, query_vector=vec, limit=top_k, with_payload=True)


def render_snippets(results) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        p = r.payload or {}
        snippet = (p.get("text") or "")[:600]
        lines.append(f"[{i}] {p.get('security_name')} / {p.get('section')}\n{snippet}")
    return "\n\n".join(lines) if lines else "(검색 컨텍스트 없음)"


def guide_prompt(issue: Dict[str, Any], snippets: str, title: str) -> str:
    comp = strip_md_link(issue.get("component", ""))
    rule = issue.get("rule", "")
    severity = issue.get("severity", "")
    line = issue.get("line", "")
    message = issue.get("message", "")
    tags = ", ".join(issue.get("tags", []))

    return (
        "다음 이슈에 대해 개발자가 바로 고칠 수 있도록 **보안 가이드**를 작성하세요.\n\n"
        "[이슈 요약]\n"
        f"- 규칙: {rule}\n"
        f"- 중요도: {severity}\n"
        f"- 파일: {comp} (line {line})\n"
        f"- 메시지: {message}\n"
        f"- 태그: {tags}\n\n"
        "[검색 컨텍스트]\n" + snippets + "\n\n"
        "[요구 출력]\n"
        f"# {title}\n"
        "- 이슈와의 연관성: 컨텍스트 중 어떤 항목이 직접 관련되는지 2~3줄\n"
        "## 개요\n"
        "(해당 보안 항목의 위험/배경)\n"
        "## 대응방안\n"
        "- 체크리스트 형태로 명확히\n"
        "## 비안전 예시\n"
        "```txt\n(일반화된 패턴; 실제 코드가 아니면 개념 예시)\n```\n"
        "## 안전 예시\n"
        "```txt\n(해결된 패턴 또는 안전 구현)\n```\n"
        "## 참고자료\n"
        "- (컨텍스트에서 유용한 항목 3~6개; 없으면 '일반 원칙' 명시)\n\n"
        "[주의]\n"
        "- 사실 위주, 과장/환상 금지. 컨텍스트에 없으면 일반 원칙으로 구분해 기술.\n"
        "- 한국어, 실무 지향, 간결하게.\n"
    )


def call_llm(client: OpenAI, model: str, prompt: str) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a senior application security engineer. Respond in Korean unless code."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def main():
    oai = OpenAI()
    qdr = QdrantClient(path=str(DB_DIR))

    issues = load_issues(AGENT_INPUTS)
    report: List[Dict[str, Any]] = []

    for i, issue in enumerate(issues, 1):
        query = build_query(issue)
        vec = embed(oai, query)
        results = search(qdr, vec, top_k=TOP_K)

        snippets = render_snippets(results)
        title = results[0].payload.get("security_name") if results else "보안 가이드"

        md = call_llm(oai, GEN_MODEL, guide_prompt(issue, snippets, title))

        comp = safe_filename(strip_md_link(issue.get("component", "unknown")))
        fname = make_filename(issue, i)
        (REPORT_DIR / fname).write_text(md, encoding="utf-8")

        report.append({
            "issue_index": i,
            "rule": issue.get("rule"),
            "component": comp,
            "line": issue.get("line"),
            "severity": issue.get("severity"),
            "tags": issue.get("tags", []),
            "search_query": issue.get("search_query"),
            "guide_file": str((REPORT_DIR / fname).relative_to(BASE)),
            "guide_title": title,
        })

        print(f"✓ [{i}/{len(issues)}] {comp}:{issue.get('line')} -> {fname}")

    (REPORT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("✅ 전체 리포트 저장:", REPORT_DIR / "report.json")


if __name__ == "__main__":
    main()
