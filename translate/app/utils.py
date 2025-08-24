from urllib.parse import urlparse
import requests
import boto3
import os

ROLES = ['controller', 'service', 'serviceimpl', 'vo']

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

def _is_feature_done(feature: dict) -> bool:
        """
        해당 feature(버킷)가 모두 처리됐는지 판단.
        """
        for r in ROLES:
            total_todo = len(feature.get('codes', {}).get(r, []))
            if total_todo > len(feature.get('egov', {}).get(r, [])):
                return False
        return True

def _cleanup_current_feature(state: dict) -> dict:
        """
        현재 feature의 큰 배열을 비우고 리스트에서 제거(pop).
        전역 *_egov / *_report는 건드리지 않음(백엔드 하위호환 보존).
        """
        i = state.get('current_feature_idx', 0)
        if i >= len(state.get('features', [])):
            return state

        b = state['features'][i]

        for section in ['codes', 'egov']:
            sec = b.get(section)
            if isinstance(sec, dict):
                for r in ROLES:
                    lst = sec.get(r)
                    if isinstance(lst, list):
                        lst.clear()

        # 리포트도 비움(features 내부 리포트만)
        rep = b.get('report', {})
        if isinstance(rep, dict):
            for r in ROLES:
                pair = rep.get(r, {})
                if isinstance(pair, dict):
                    lst1 = pair.get('conversion')
                    lst2 = pair.get('generation')
                    if isinstance(lst1, list): lst1.clear()
                    if isinstance(lst2, list): lst2.clear()

        # 검색 캐시/진행 상태 정리
        state['retrieved'] = []
        state['next_role'] = ''

        # 버킷 제거
        state['features'].pop(i)

        # 인덱스 보정
        if not state['features']:
            state['current_feature_idx'] = 0
        elif i >= len(state['features']):
            state['current_feature_idx'] = len(state['features']) - 1

        return state

def _advance_and_cleanup_finished_features(state: dict) -> dict:
        """
        앞쪽에 완료된 feature가 연속으로 있으면 모두 정리.
        현재 인덱스에서 시작해 완료면 계속 pop, 미완료 만나면 중단.
        """
        while state.get('features'):
            i = state.get('current_feature_idx', 0)
            if i >= len(state['features']):
                state['current_feature_idx'] = 0
                break

            b = state['features'][i]
            if _is_feature_done(b):
                _cleanup_current_feature(state)
            else:
                break
        return state