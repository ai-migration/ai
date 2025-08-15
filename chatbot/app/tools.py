# tools.py
"""
도메인 도우미/유틸 모듈 — 추후 LangChain @tool 로 확장 가능
"""
from typing import List, Dict

ROUTE_ALIASES: List[Dict[str, str]] = [
    {"alias": "변환", "label": "변환 하기", "url": "/support/transform/transformation"},
    {"alias": "보안", "label": "AI 보안 검사", "url": "/support/security/scan"},
    {"alias": "전자정부", "label": "전자정부프레임워크 가이드", "url": "/support/guide/egovframework"},
]

def alias_suggestions(text: str, limit: int = 3) -> List[Dict[str, str]]:
    text = (text or "").lower()
    hits = []
    for a in ROUTE_ALIASES:
        if a["alias"] in text:
            hits.append({"label": a["label"], "url": a["url"]})
            if len(hits) >= limit:
                break
    return hits
