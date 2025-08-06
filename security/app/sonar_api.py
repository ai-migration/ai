import requests
from pprint import pprint
from collections import defaultdict

# 설정값
SONAR_URL = "http://localhost:9000"
TOKEN = "sqa_9dd9116bac1d18488acc6c9d8eaa64936216bba8"
PROJECT_KEY = "test2"

# 인증 방식 (Basic Auth 형태, 사용자명에 토큰 넣고 비번은 빈칸)
AUTH = (TOKEN, '')

# 품질 게이트 상태 조회
def get_quality_gate_status():
    url = f"{SONAR_URL}/api/qualitygates/project_status"
    params = {"projectKey": PROJECT_KEY}
    res = requests.get(url, params=params, auth=AUTH)
    return res.json()

# 메트릭 (버그/취약점/스멜) 조회
def get_project_metrics():
    url = f"{SONAR_URL}/api/measures/component"
    params = {
        "component": PROJECT_KEY,
        "metricKeys": "bugs,vulnerabilities,code_smells"
    }
    res = requests.get(url, params=params, auth=AUTH)

    return res.json()

def group_issues_by_file(issues_json):
    issues = issues_json.get("issues", [])
    grouped = defaultdict(list)

    for issue in issues:
        file_path = issue.get("component", "").split(":")[-1]
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

# 취약점 조회
def get_vulnerability_issues():
    url = f"{SONAR_URL}/api/issues/search"
    params = {
        "componentKeys": PROJECT_KEY,
        "types": "BUG,VULNERABILITY,CODE_SMELL",
        "ps": 500  # 최대 500개까지
    }
    res = requests.get(url, params=params, auth=AUTH)
    critical_vulns = group_issues_by_file(res.json())
    print_issues_by_file(critical_vulns)
    return res.json()


# 실행
if __name__ == "__main__":
    print("📊 품질 게이트 상태:")
    pprint(get_quality_gate_status())

    print("\n🐞 메트릭 요약 (버그/취약점/코드 스멜):")
    pprint(get_project_metrics())

    print("\n🔐 취약점 이슈 요약:")
    pprint(get_vulnerability_issues())
