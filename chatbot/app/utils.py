# utils.py
"""
경량 파일 유틸 — 추후 ingest 파이프라인에서 사용
"""
import os
from typing import List, Tuple

def iter_text_files(root: str, exts=(".txt", ".md")) -> List[Tuple[str, str]]:
    out = []
    if not os.path.isdir(root):
        return out
    for r, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith(exts):
                p = os.path.join(r, f)
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                        out.append((f, fp.read()))
                except Exception:
                    pass
    return out
