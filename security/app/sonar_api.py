# sonar_api.py
import requests
import json
import time
from pathlib import Path
from collections import defaultdict
from pprint import pprint

# ===== 설정 =====
SONAR_URL = "http://localhost:9000"
TOKEN = "sqa_d92dfa34bb6849d9dfc4dd9a212a52f32a0e273b"
PROJECT_KEY = "test01"
AUTH = (TOKEN, '')  # 토큰 인증
PAGE_SIZE = 500

# ===== 공통 유틸 =====
def ensure_dir(path: str | Path):
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

def save_json(obj, path: str | Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    print(f"💾 저장 완료: {path}")

def build_search_query(message: str, tags):
    msg = (message or "").strip()
    tag_str = " ".join([str(t).strip() for t in (tags or []) if t])
    return f"{msg} {tag_str}".strip()

# ===== 품질/메트릭 =====
def get_quality_gate_status():
    url = f"{SONAR_URL}/api/qualitygates/project_status"
    params = {"projectKey": PROJECT_KEY}
    res = requests.get(url, params=params, auth=AUTH)
    res.raise_for_status()
    return res.json()

def get_project_metrics():
    url = f"{SONAR_URL}/api/measures/component"
    params = {"component": PROJECT_KEY, "metricKeys": "bugs,vulnerabilities,code_smells"}
    res = requests.get(url, params=params, auth=AUTH)
    res.raise_for_status()
    return res.json()

# ===== 이슈 수집 (페이지네이션) =====
def fetch_all_issues():
    print("🚀 SonarQube 이슈 수집 시작...\n")
    page = 1
    all_issues, components = [], []
    total, effort_total = 0, 0

    while True:
        url = f"{SONAR_URL}/api/issues/search"
        params = {
            "componentKeys": PROJECT_KEY,
            "types": "BUG,VULNERABILITY,CODE_SMELL",
            "ps": PAGE_SIZE,
            "p": page
        }
        res = requests.get(url, params=params, auth=AUTH)
        res.raise_for_status()
        data = res.json()

        issues = data.get("issues", [])
        if not issues:
            break

        all_issues.extend(issues)

        if page == 1:
            components = data.get("components", [])
            total = data.get("total", len(issues))
            effort_total = data.get("effortTotal", 0)

        print(f"📦 {page}페이지 수집 완료 - 누적 이슈 수: {len(all_issues)}")
        page += 1
        time.sleep(0.2)  # 서버 과부하 방지

    print("\n✅ 모든 페이지 수집 완료.")
    return {
        "issues": all_issues,
        "components": components,
        "effortTotal": effort_total,
        "total": total
    }

# ===== 이슈 그룹핑(출력용) =====
def group_issues_by_file(issues_json):
    issues = issues_json.get("issues", [])
    grouped = defaultdict(list)
    for issue in issues:
        file_path = (issue.get("component", "") or "").split(":")[-1]
        grouped[file_path].append({
            "type": issue.get("type"),
            "message": issue.get("message"),
            "severity": issue.get("severity"),
            "line": issue.get("line", "-"),
            "rule": issue.get("rule")
        })
    return grouped

def print_issues_by_file(grouped_issues):
    if not grouped_issues:
        print("✅ 문제 없음")
        return
    for file, issues in grouped_issues.items():
        print(f"📄 {file} - 총 {len(issues)}건")
        for issue in issues:
            print(f"  🔸 [{issue['type']} | {issue['severity']}] {issue['message']}")
            print(f"     ↪ Line {issue['line']}, Rule: {issue['rule']}")
        print()

# ===== agent_inputs 생성 =====
def extract_agent_inputs(all_issues_json):
    issues = all_issues_json.get("issues", [])
    agent_inputs = []
    for issue in issues:
        rule = issue.get("rule", "") or ""
        message = issue.get("message", "") or ""
        tags = issue.get("tags", []) or []
        severity = issue.get("severity", "") or ""
        component_raw = issue.get("component", "") or ""
        component = component_raw.split(":")[-1] if component_raw else ""
        line = issue.get("line", "-")
        if line is None:
            line = "-"
        agent_inputs.append({
            "rule": rule,
            "message": message,
            "tags": [str(t) for t in tags],
            "severity": severity,
            "component": component,
            "line": line,
            "search_query": build_search_query(message, tags)
        })
    return agent_inputs

# ===== 메인 실행 =====
if __name__ == "__main__":
    # 출력 폴더
    out_dir = ensure_dir("outputs")

    print("📊 품질 게이트 상태:")
    qg = get_quality_gate_status()
    pprint(qg)
    save_json(qg, out_dir / "quality_gate.json")

    print("\n🐞 메트릭 요약 (버그/취약점/코드 스멜):")
    metrics = get_project_metrics()
    pprint(metrics)
    save_json(metrics, out_dir / "metrics.json")

    print("\n🔎 이슈 전체 수집(페이지네이션):")
    all_issues = fetch_all_issues()
    save_json(all_issues, out_dir / "sonarqube_issues_combined.json")

    print("\n🗂 파일별 이슈 요약:")
    grouped = group_issues_by_file(all_issues)
    print_issues_by_file(grouped)

    print("\n🤖 agent_inputs 생성:")
    agent_inputs = extract_agent_inputs(all_issues)
    save_json(agent_inputs, out_dir / "agent_inputs.json")

    print("\n✅ 완료! 생성 파일:")
    print(f" - {out_dir / 'quality_gate.json'}")
    print(f" - {out_dir / 'metrics.json'}")
    print(f" - {out_dir / 'sonarqube_issues_combined.json'}")
    print(f" - {out_dir / 'agent_inputs.json'}")
