# security/app/utils.py
# 역할: 입력으로 들어온 파일 경로(s3://, http(s)://, 로컬 zip/폴더)를 워크스페이스로 내려받고(또는 복사),
#       ZIP이면 압축 해제까지 수행하여 sonar-scanner가 바로 돌 수 있는 프로젝트 루트를 반환한다.
#       반환값: (project_root: Path, project_name: str)  ← project_name == ZIP(확장자 제외)


from urllib.parse import urlparse
import requests
import boto3
import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional, Tuple, List

# --- (conversion utils에서 가져온 다운로드 유틸) ---
def _is_s3_uri(p): return isinstance(p, str) and p.startswith("s3://")
def _is_http_uri(p): return isinstance(p, str) and (p.startswith("http://") or p.startswith("https://"))
def _parse_s3_uri(uri): 
    o = urlparse(uri); 
    return o.netloc, o.path.lstrip('/')

def _download_s3_to(dir_path: str, s3_uri: str) -> str:
    """S3에서 ZIP을 내려받아 로컬에 저장, 저장된 ZIP 경로를 반환"""
    os.makedirs(dir_path, exist_ok=True)
    bucket, key = _parse_s3_uri(s3_uri)
    local_zip = os.path.join(dir_path, os.path.basename(key) or "input.zip")
    boto3.client("s3").download_file(bucket, key, local_zip)
    return local_zip

def _download_http_to(dir_path: str, url: str) -> str:
    """HTTP/HTTPS(프리사인 포함)에서 ZIP을 내려받아 로컬에 저장, 저장된 ZIP 경로를 반환"""
    os.makedirs(dir_path, exist_ok=True)
    local_zip = os.path.join(dir_path, "input.zip")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(local_zip, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
    return local_zip
# --------------------------------

def _extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """ZIP을 dest_dir에 해제"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(dest_dir)

def _single_toplevel_dir(path: Path) -> Optional[Path]:
    """
    압축 해제 디렉토리 바로 아래에 '단일 상위 폴더'만 있는 경우 그 폴더를 반환.
    (e.g., zip 안에 myproj/ 가 하나 있고, 그 아래에 소스들이 있는 형태)
    """
    if not path.exists():
        return None
    items: List[Path] = [p for p in path.iterdir() if not p.name.startswith('.')]
    if len(items) == 1 and items[0].is_dir():
        return items[0]
    return None

def _basename_from_source(src_path: str) -> str:
    """
    ZIP/폴더/파일/URL로부터 '기본 이름'을 추출.
    - ZIP이면 확장자 제거
    - 폴더면 폴더명
    - 파일이면 파일 스템
    - URL이면 path basename
    """
    if _is_s3_uri(src_path) or _is_http_uri(src_path):
        path_part = urlparse(src_path).path
        name = os.path.basename(path_part) or "input.zip"
    else:
        name = os.path.basename(src_path)

    stem, ext = os.path.splitext(name)
    return stem or "input"

def _normalize_project_root(work: Path, desired_name: str) -> Path:
    """
    압축해제/복사 직후의 work 내용물을 'work/desired_name' 하위로 정리.
    - 단일 최상위 폴더가 있고 이름이 다르면 rename
    - 파일들이 work 루트에 흩어져 있으면 work/desired_name을 만들고 모두 이동
    """
    print(f"[normalize] 원하는 프로젝트 폴더명: {desired_name}")
    single = _single_toplevel_dir(work)
    dest = work / desired_name

    if single:
        if single.name != desired_name:
            print(f"[normalize] 단일 폴더 발견: {single.name} → {desired_name} 로 이름 변경")
            if dest.exists():
                shutil.rmtree(dest)
            single.rename(dest)
        else:
            print(f"[normalize] 단일 폴더명이 이미 일치: {single.name}")
            dest = single
    else:
        # 흩어진 경우: 새 폴더 만들고 모두 이동
        dest.mkdir(parents=True, exist_ok=True)
        for item in list(work.iterdir()):
            if item.name == desired_name:
                continue
            shutil.move(str(item), str(dest / item.name))
        print(f"[normalize] 흩어진 파일들을 {desired_name}/ 하위로 이동 완료")

    return dest


def prepare_workspace_from_input(src_path: str, job_id: str) -> Tuple[Path, str]:
    """
    역할:
      - security 작업용 워크스페이스 디렉토리 생성(job_id 기준)
      - src_path가 s3/http/로컬(zip/폴더/단일파일)인지 판단
      - ZIP은 해제, 폴더는 복사, 파일은 복사
      - 최종적으로 'work/{ZIP이름}/' 형태로 표준화하여 프로젝트 루트를 반환
    반환: (project_root: Path, project_name: str)
          project_name은 ZIP(확장자 제외) 또는 폴더명
    """
    base = Path(__file__).resolve().parent / "workspace"
    work = base / str(job_id)

    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    desired_name = _basename_from_source(src_path)
    print(f"[workspace] job_id={job_id}, 입력명→프로젝트명: {desired_name}")

    if _is_s3_uri(src_path):
        local_zip = Path(_download_s3_to(work.as_posix(), src_path))
        _extract_zip(local_zip, work)
    elif _is_http_uri(src_path):
        local_zip = Path(_download_http_to(work.as_posix(), src_path))
        _extract_zip(local_zip, work)
    else:
        p = Path(src_path)
        if not p.exists():
            raise FileNotFoundError(f"Source not found: {src_path}")
        if p.is_file() and p.suffix.lower() == ".zip":
            _extract_zip(p, work)
        elif p.is_dir():
            for item in p.iterdir():
                dest = work / item.name
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
        else:
            shutil.copy2(p, work / p.name)

    # 표준화: 최종 프로젝트 루트를 work/{desired_name} 로 정리
    project_root = _normalize_project_root(work, desired_name)
    print(f"[workspace] 프로젝트 루트: {project_root}")
    return project_root, desired_name