# security/app/security_pipeline.py
# 역할: security 파이프라인을 한 번에 실행하는 진입점.
#       - utils.prepare_workspace_from_input()로 작업 폴더/프로젝트 루트 구성
#       - sonar-project.properties에 projectKey/host.url 주입
#       - sonar-scanner → sonar_api.py → run_refactor.py 순차 실행
#       - 실행 결과 코드/메타 반환 

import os, re, sys, subprocess, shutil, stat
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from security.app.utils import prepare_workspace_from_input
from dotenv import load_dotenv
import json

# 결과 수집 유틸 1
def _read_json_if_exists(p: Path):
    """존재하면 JSON 로드, 없으면 None."""
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except Exception:
        return None
    
# 결과 수집 유틸 2
def _gather_security_result(outputs_dir: Path) -> dict:
    """
    역할: outputs/security_reports/ 하위 산출물을 백엔드가 S3에 올릴 수 있도록
         하나의 dict(result)로 정리한다.
    """
    
    reports = outputs_dir / "security_reports"
    root    = outputs_dir
    def load_first(name: str):
        return (_read_json_if_exists(reports / name)
                or _read_json_if_exists(root / name))
    # def _read_both(fname: str):
    #     """outputs/ 우선, 없으면 outputs/security_reports/ 에서 로드"""
    #     return (_read_json_if_exists(base / fname)
    #             or _read_json_if_exists(reports / fname))

    # result: dict = {
    #     "agentInputs": _read_both("agent_inputs.json"),
    #     "metrics":     _read_both("metrics.json"),
    #     "qualityGate": _read_both("quality_gate.json"),
    #     "issues":      _read_both("sonarqube_issues_combined.json"),
    #     "reportJson":  _read_json_if_exists(reports / "report.json"),  # report.json은 가이드 생성 후 reports에 존재
    #     "markdowns": []
    # }
    result: dict = {
        "agentInputs": None,   # outputs/agent_inputs.json
        "metrics": None,       # outputs/metrics.json
        "qualityGate": None,   # outputs/quality_gate.json
        "issues": None,        # outputs/sonarqube_issues_combined.json
        "reportJson": None,    # outputs/security_reports/report.json (있을 때)
        "markdowns": []        # [{name, text}]
    }
    result["agentInputs"] = _read_json_if_exists(reports / "agent_inputs.json")
    result["metrics"]     = _read_json_if_exists(reports / "metrics.json")
    result["qualityGate"] = _read_json_if_exists(reports / "quality_gate.json")
    result["issues"]      = _read_json_if_exists(reports / "sonarqube_issues_combined.json")
    result["reportJson"]  = _read_json_if_exists(reports / "report.json")

    if reports.exists():
        for p in reports.glob("*.md"):
            try:
                result["markdowns"].append({"name": p.name, "text": p.read_text(encoding="utf-8")})
            except Exception:
                pass
    return result

def _on_rm_error(func, path, exc_info):
    # Windows 읽기전용 파일 삭제 대응
    os.chmod(path, stat.S_IWRITE)
    func(path)

def _cleanup_local(job_id: int):
    base = Path(__file__).parent
    targets = [
        base / "workspace" / str(job_id),
        base / "outputs" / str(job_id),  # ← 잡별 출력 폴더만 지움
    ]
    for t in targets:
        if t.exists():
            shutil.rmtree(t, onerror=_on_rm_error)

def _upsert_properties(path: Path, kv: Dict[str, str]) -> None:
    """
    역할: sonar-project.properties에 key=value upsert.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for k, v in kv.items():
        pat = re.compile(rf"(?m)^\s*{re.escape(k)}\s*=.*$")
        if pat.search(text):
            text = pat.sub(f"{k}={v}", text)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += f"{k}={v}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def _run(cmd: str, cwd: Optional[Path] = None, env: Optional[Dict[str,str]] = None, encoding: str="utf-8", errors: str="replace") -> Tuple[int, str, str]:
    """
    역할: 커맨드 실행(표준출력/오류 캡처), (returncode, stdout, stderr) 반환
    - Windows 콘솔 인코딩 이슈 방지를 위해 UTF-8로 디코딩(+에러는 대체) 고정
    """
    print(f"\n$ {cmd}")
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, shell=True,
                       text=True, capture_output=True, env=env, encoding=encoding, errors=errors)
    print("✅ STDOUT:\n", p.stdout)
    print("⚠️ STDERR:\n", p.stderr)
    return p.returncode, p.stdout, p.stderr

def run_security_pipeline(*,
                          user_id: int,
                          job_id: int,
                          file_path: str,
                          sonar_scanner_cmd: str = "sonar-scanner",
                          python_exec: str = sys.executable,) -> Dict[str, object]:
    """
    역할: Security 파이프라인 전체 실행.
    반환: {
      status, exitCode, projectKey, projectRootPath, projectRootName, outputsDir,
      checkpoints: [ {step, ok, details} ... ]
    }
    """

    if not file_path:
        raise ValueError("file_path is required")
    
    # env에서 민감값 가져오기
    load_dotenv()
    url    = os.getenv("SONAR_URL", "http://localhost:9000")
    token  = os.getenv("SONAR_TOKEN")
    apiKey = os.getenv("OPENAI_API_KEY")


    checkpoints: List[Dict[str, str]] = []

    # 1) 작업 폴더 준비 (ZIP 다운로드/압축해제 or 폴더 복사)
    project_root, project_name = prepare_workspace_from_input(file_path, str(job_id))
    pj_key = project_name  # projectKey 규칙: ZIP이름 == 압축해제 폴더명 == projectKey
    checkpoints.append({"step": "workspace", "ok": "true",
                        "details": f"project_root={project_root}, project_name={project_name}"})
    
    # 2) 환경 확인 로그
    print(f"[env] SONAR_URL={url}")
    print(f"[env] SONAR_PROJECT_KEY={pj_key}")
    print(f"[env] SONAR_TOKEN={'<set>' if token else '<missing>'}")

    # 3) properties upsert (프로젝트 루트에 파일 생성/치환)
    props = project_root / "sonar-project.properties"
    _upsert_properties(props, {
        "sonar.projectKey": pj_key,
        "sonar.host.url": url,
        # 필요 시 다음도 주입 가능:
        # "sonar.sources": ".",
        # "sonar.sourceEncoding": "UTF-8",
    })
    checkpoints.append({"step": "properties", "ok": "true",
                        "details": f"props={props}"})

    # 공통 ENV 구성 (토큰/URL/프로젝트 키를 후속 단계로 전달)
    env = os.environ.copy()
    if token:
        env["SONAR_TOKEN"] = token
    env["SONAR_URL"] = url
    env["SONAR_PROJECT_KEY"] = pj_key
    env["PYTHONIOENCODING"] = "utf-8"
    if apiKey: env["OPENAI_API_KEY"] = apiKey

    # 4) sonar-scanner
    rc, out, err = _run(sonar_scanner_cmd, cwd=project_root, env=env)
    scanner_ok = (rc == 0)
    # 추가 확인: .scannerwork 존재 여부
    scannerwork = project_root / ".scannerwork"
    if scannerwork.exists():
        details = f"scannerwork ok: {scannerwork}"
    else:
        details = ".scannerwork 미생성(로그 확인 필요)"
    checkpoints.append({"step": "sonar-scanner", "ok": str(scanner_ok).lower(), "details": details})
    if not scanner_ok:
        fail_outputs_dir = Path(__file__).parent / "outputs" / str(job_id)
        ret = {
            "status": f"FAIL_SCAN({rc})",
            "exitCode": rc,
            "projectKey": pj_key,
            "projectRootPath": str(project_root),
            "projectRootName": project_name,
            "outputsDir": str(fail_outputs_dir),
            "checkpoints": checkpoints
        }
        if os.getenv("KEEP_LOCAL", "0") != "1":
            try:
                _cleanup_local(job_id)
            except Exception as e:
                print(f"[cleanup] skip error: {e}")
        return ret
    
    app_dir = Path(__file__).parent
    outputs_dir = app_dir / "outputs" / str(job_id)
    env["JOB_ID"] = str(job_id)

    # 5) sonar_api.py (CE 완료 대기 + 이슈 수집)
    rc, out, err = _run(f'"{python_exec}" -X utf8 sonar_api.py', cwd=app_dir, env=env)
    api_ok = (rc == 0)
    # 산출 확인: report.json or outputs/security_reports
    reports_dir = outputs_dir / "security_reports"
    report_json = app_dir / "report.json"
    if reports_dir.exists() or report_json.exists():
        details = f"reports_dir={reports_dir.exists()}, report.json={report_json.exists()}"
    else:
        details = "보고서 산출물 미확인"
    checkpoints.append({"step": "sonar_api", "ok": str(api_ok).lower(), "details": details})

    if not api_ok:
        ret = {
            "status": f"FAIL_API({rc})",
            "exitCode": rc,
            "projectKey": pj_key,
            "projectRootPath": str(project_root),
            "projectRootName": project_name,
            "outputsDir": str(outputs_dir),
            "checkpoints": checkpoints,
        }
        if os.getenv("KEEP_LOCAL", "0") != "1":
            try:
                _cleanup_local(job_id)
            except Exception as e:
                print(f"[cleanup] skip error: {e}")
        return ret

    # 6) run_refactor.py (리포트/가이드 생성)
    rc, out, err = _run(f'"{python_exec}" run_refactor.py', cwd=app_dir, env=env)
    ref_ok = (rc == 0)
    # 산출 확인: security_reports/*.md 개수
    md_count = 0
    if reports_dir.exists():
        md_count = len([p for p in reports_dir.glob("*.md")])
    checkpoints.append({"step": "run_refactor", "ok": str(ref_ok).lower(),
                        "details": f"md_count={md_count}, outputs_dir={reports_dir}"})
    result_payload = _gather_security_result(outputs_dir)


    status = "SUCCESS" if ref_ok else f"FAIL_REFACTOR({rc})"
    ret = {
        "status": status,
        "exitCode": rc,
        "projectKey": pj_key,
        "projectRootPath": str(project_root),
        "projectRootName": project_name,
        "outputsDir": str(outputs_dir),
        "checkpoints": checkpoints,

        # 백엔드 업로드용 실데이터
        "eventType": "SecurityFinished",
        "userId": user_id,
        "jobId": job_id,
        "result": result_payload,
    }

    # 성공/실패와 무관하게 로컬 정리 (디버깅 시 KEEP_LOCAL=1 로 보존)
    if os.getenv("KEEP_LOCAL", "0") != "1":
        try:
            _cleanup_local(job_id)
        except Exception as e:
            print(f"[cleanup] skip error: {e}")
    return ret

