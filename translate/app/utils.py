from urllib.parse import urlparse
import requests
import boto3
import os

def _is_s3_uri(p): return isinstance(p, str) and p.startswith("s3://")
def _is_http_uri(p): return isinstance(p, str) and (p.startswith("http://") or p.startswith("https://"))
def _parse_s3_uri(uri): o=urlparse(uri); return o.netloc, o.path.lstrip('/')

def _download_s3_to(dir_path: str, s3_uri: str) -> str:
    os.makedirs(dir_path, exist_ok=True)
    bucket, key = _parse_s3_uri(s3_uri)
    local_zip = os.path.join(dir_path, os.path.basename(key) or "input.zip")
    boto3.client("s3").download_file(bucket, key, local_zip)
    return local_zip

def _download_http_to(dir_path: str, url: str) -> str:
    # 프리사인 URL 포함 모든 http(s) 다운로드
    os.makedirs(dir_path, exist_ok=True)
    local_zip = os.path.join(dir_path, "input.zip")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(local_zip, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
    return local_zip
