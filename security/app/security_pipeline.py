# security/app/security_pipeline.py
# 역할: security 파이프라인을 한 번에 실행하는 진입점.
#       - utils.prepare_workspace_from_input()로 작업 폴더/프로젝트 루트 구성
#       - sonar-project.properties에 projectKey/host.url 주입
#       - sonar-scanner → sonar_api.py → run_refactor.py 순차 실행
#       - 실행 결과 코드/메타 반환 

import os, re, sys, subprocess
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from security.app.utils import prepare_workspace_from_input
from dotenv import load_dotenv

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
        return {
            "status": f"FAIL_SCAN({rc})",
            "exitCode": rc,
            "projectKey": pj_key,
            "projectRootPath": str(project_root),
            "projectRootName": project_name,
            "outputsDir": str(Path(__file__).parent / "outputs"),
            "checkpoints": checkpoints,
        }
    app_dir = Path(__file__).parent
    outputs_dir = app_dir / "outputs"

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
        return {
            "status": f"FAIL_API({rc})",
            "exitCode": rc,
            "projectKey": pj_key,
            "projectRootPath": str(project_root),
            "projectRootName": project_name,
            "outputsDir": str(outputs_dir),
            "checkpoints": checkpoints,
        }

    # 6) run_refactor.py (리포트/가이드 생성)
    rc, out, err = _run(f'"{python_exec}" run_refactor.py', cwd=app_dir, env=env)
    ref_ok = (rc == 0)
    # 산출 확인: security_reports/*.md 개수
    md_count = 0
    if reports_dir.exists():
        md_count = len([p for p in reports_dir.glob("*.md")])
    checkpoints.append({"step": "run_refactor", "ok": str(ref_ok).lower(),
                        "details": f"md_count={md_count}, outputs_dir={reports_dir}"})

    status = "SUCCESS" if ref_ok else f"FAIL_REFACTOR({rc})"
    return {
        "status": status,
        "exitCode": rc,
        "projectKey": pj_key,
        "projectRootPath": str(project_root),
        "projectRootName": project_name,
        "outputsDir": str(outputs_dir),
        "checkpoints": checkpoints,
    }

