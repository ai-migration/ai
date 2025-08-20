# chunk_refactor.py
# -----------------
# 역할: security_guides.json(.jsonl) → outputs/chunks.jsonl
#  - 텍스트/코드 섹션 자동 인식 + 청킹(토큰 단위)
#  - 코드 섹션 누락 방지(다양한 키 매핑) + 언어 추정(lang)
#  - 임베딩/인덱싱은 하지 않음(FAISS는 build_index.py에서)

import os, json, re, argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple

# 선택적 토크나이저 (없으면 간단 Fallback)
try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENC = None

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
OUT_DIR  = BASE / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 입력 파일 (json 또는 jsonl)
IN_JSON  = Path(os.getenv("DATA_JSON",  DATA_DIR / "security_guides.json"))
IN_JSONL = Path(os.getenv("DATA_JSONL", DATA_DIR / "security_guides.jsonl"))

# 출력 파일
CHUNKS_OUT = OUT_DIR / "chunks.jsonl"

# 청킹 파라미터 (환경변수로 오버라이드 가능)
TXT_MAX = int(os.getenv("TXT_MAX", "480"))
TXT_OV  = int(os.getenv("TXT_OV", "64"))
CODE_MAX = int(os.getenv("CODE_MAX", "1000"))
CODE_OV  = int(os.getenv("CODE_OV", "100"))

# ---------------- 공용 유틸 ----------------

def tokenize(text: str) -> List[int]:
    if _ENC is None:
        # 매우 단순한 대체: 문자 단위
        return [ord(c) for c in (text or "")]
    return _ENC.encode(text or "")

def detokenize(ids: List[int]) -> str:
    if _ENC is None:
        return "".join(chr(i) for i in ids)
    return _ENC.decode(ids)

def chunk_by_tokens(text: str, max_tokens: int, overlap: int, *, min_chars: int = 20) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    ids = tokenize(text)
    chunks: List[str] = []
    step = max(1, max_tokens - overlap)
    for i in range(0, len(ids), step):
        window = ids[i:i+max_tokens]
        if not window:
            break
        ch = detokenize(window).strip()
        if len(ch) >= min_chars:
            chunks.append(ch)
        if i + max_tokens >= len(ids):
            break
    return chunks

def _parse_json_or_jsonl_str(s: str) -> List[Dict[str, Any]]:
    # JSON array 우선, 아니면 jsonl로 파싱
    try:
        obj = json.loads(s)
        if isinstance(obj, list):
            return obj
        raise ValueError("not a list")
    except Exception:
        rows = []
        for line in s.splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows

def load_guides() -> List[Dict[str, Any]]:
    if IN_JSON.exists():
        raw = IN_JSON.read_text(encoding="utf-8-sig")
        try:
            data = _parse_json_or_jsonl_str(raw)
            # 혹시 jsonl가 json 파일로 들어왔으면 정규화
            if raw.lstrip().startswith("{"):
                IN_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return data
        except Exception:
            pass
    if IN_JSONL.exists():
        data = _parse_json_or_jsonl_str(IN_JSONL.read_text(encoding="utf-8-sig"))
        # 통일을 위해 json으로도 저장
        IN_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data
    raise FileNotFoundError("security_guides.json(.jsonl) 파일을 찾을 수 없습니다.")

# ---------------- 섹션 키셋/매핑 ----------------

OV_KEYS   = {"개요","요약","설명","overview","summary","description"}
MIT_KEYS  = {
    "보안대책","대책","대응","대응방안","가이드","조치",
    "mitigation","countermeasure","countermeasures","guideline",
    "measures","remediation","prevention","controls"
}
REF_KEYS  = {"참고자료","참고","레퍼런스","링크","references","reference","refs","sources","links","documents"}

# 코드 섹션: 다양한 명칭을 폭넓게 수용
WEAK_KEYS = {
    "취약","취약코드","취약예시","취약예시코드",
    "unsafe","unsafe_code","unsafeexamples","unsafe_examples",
    "vuln","vulncode","vuln_code","weak","bad","insecure"
}
SAFE_KEYS = {
    "안전","안전코드","안전예시","안전예시코드",
    "safe","safe_code","safeexamples","safe_examples",
    "secure","fixed","good","hardened","secure_code","safecode"
}

_norm = lambda s: re.sub(r"[^a-z0-9가-힣]","", (s or "").lower())
OV_N={_norm(k) for k in OV_KEYS}; MI_N={_norm(k) for k in MIT_KEYS}; RE_N={_norm(k) for k in REF_KEYS}
WK_N={_norm(k) for k in WEAK_KEYS}; SF_N={_norm(k) for k in SAFE_KEYS}

def _stringify(v: Any) -> str:
    if v is None: return ""
    if isinstance(v, str): return v
    if isinstance(v, (int, float)): return str(v)
    if isinstance(v, list): return "\n".join(_stringify(x) for x in v if x)
    if isinstance(v, dict):
        for k in ["content","text","value","body","desc","description","code","snippet"]:
            if k in v and v[k]:
                return _stringify(v[k])
        # dict이지만 특정 키가 없으면 value들 연결
        return "\n".join(_stringify(x) for x in v.values() if x)
    return ""

def guess_lang(code: str) -> str:
    c = code or ""
    if re.search(r"\bpublic\s+class\b|System\.out\.println|@RequestMapping", c): return "java"
    if re.search(r"\bimport\s+\w+|def\s+\w+\(|print\(", c): return "python"
    if re.search(r"function\s+\w+\(|console\.log|=>\s*\{", c): return "javascript"
    if re.search(r"#include\s*<\w+>|int\s+main\s*\(", c): return "c"
    if re.search(r"SELECT\s+.+\s+FROM\b|INSERT\s+INTO\b|UPDATE\s+\w+\s+SET\b", c, re.I): return "sql"
    if re.search(r"using\s+System;|Console\.WriteLine", c): return "csharp"
    if re.search(r"<%@\s*page|<jsp:|<c:out", c, re.I): return "jsp"
    return "txt"

def _classify_sections(sections: Any) -> Tuple[str,str,str,str,str]:
    """sections(any) → (overview, mitigation, references, weak_code, safe_code)"""
    ov, mi, rf, wk, sf = [], [], [], [], []

    def push(name: str, val: Any):
        raw_name = (name or "")
        key = _norm(raw_name)
        txt = _stringify(val)
        if not txt:
            return

        # 1차: 사전 정의 키셋
        if key in OV_N:  ov.append(txt); return
        if key in MI_N:  mi.append(txt); return
        if key in RE_N:  rf.append(txt); return
        if key in WK_N:  wk.append(txt); return
        if key in SF_N:  sf.append(txt); return

        # 2차: 이름 휴리스틱 (vuln/unsafe/취약 vs safe/secure/안전 + code/예시)
        low = raw_name.lower()
        if any(t in low for t in ["vuln","unsafe","취약","weak","insecure"]) and any(t in low for t in ["code","예시","example"]):
            wk.append(txt); return
        if any(t in low for t in ["safe","secure","안전","fixed","hardened"]) and any(t in low for t in ["code","예시","example"]):
            sf.append(txt); return

        # 3차: 중첩 dict 내부 weak/safe 키 추적
        if isinstance(val, dict):
            for wkey in WEAK_KEYS:
                if wkey in val and val[wkey]:
                    wk.append(_stringify(val[wkey])); break
            for skey in SAFE_KEYS:
                if skey in val and val[skey]:
                    sf.append(_stringify(val[skey])); break

    if isinstance(sections, dict):
        for k, v in sections.items():
            push(k, v)
    elif isinstance(sections, list):
        for it in sections:
            if not isinstance(it, dict): 
                continue
            name = it.get("name") or it.get("title") or it.get("section") or ""
            content = it.get("content") or it.get("text") or it.get("value") or it.get("body") or it
            push(name, content)
            ex = it.get("examples") or it.get("example") or it.get("codes") or it.get("code")
            if isinstance(ex, dict):
                for wkey in WEAK_KEYS:
                    if wkey in ex and ex[wkey]:
                        wk.append(_stringify(ex[wkey])); break
                for skey in SAFE_KEYS:
                    if skey in ex and ex[skey]:
                        sf.append(_stringify(ex[skey])); break

    uniq = lambda lst: "\n".join(dict.fromkeys([x.strip() for x in lst if x and x.strip()]))
    return uniq(ov), uniq(mi), uniq(rf), uniq(wk), uniq(sf)

# ---------------- 메인 ----------------

def main():
    ap = argparse.ArgumentParser(description="Chunk security guides into chunks.jsonl")
    ap.add_argument("--txt-max", type=int, default=TXT_MAX)
    ap.add_argument("--txt-ov", type=int, default=TXT_OV)
    ap.add_argument("--code-max", type=int, default=CODE_MAX)
    ap.add_argument("--code-ov", type=int, default=CODE_OV)
    args = ap.parse_args()

    guides = load_guides()
    chunks: List[Dict[str, Any]] = []

    for i, g in enumerate(guides):
        sid = str(g.get("security_id") or f"guide_{i}")
        sname = g.get("security_name", sid)
        secs = g.get("sections", {}) or {}

        ov, mi, rf, wk, sf = _classify_sections(secs)

        # 텍스트 섹션
        for section, text in [("overview", ov), ("mitigation", mi), ("references", rf)]:
            for j, ch in enumerate(chunk_by_tokens(text, args.txt_max, args.txt_ov, min_chars=20)):
                chunks.append({
                    "id": f"{sid}::TXT::{section}::{j}",
                    "text": ch,
                    "metadata": {
                        "parent_id": sid,
                        "security_name": sname,
                        "section": section,
                        "is_code": False,
                        "lang": "txt",
                    }
                })

        # 코드 섹션 (is_code: true 보장)
        for section, code in [("unsafe_examples", wk), ("safe_examples", sf)]:
            for j, ch in enumerate(chunk_by_tokens(code, args.code_max, args.code_ov, min_chars=5)):
                chunks.append({
                    "id": f"{sid}::CODE::{section}::{j}",
                    "text": ch,
                    "metadata": {
                        "parent_id": sid,
                        "security_name": sname,
                        "section": section,
                        "is_code": True,                 # ★ 중요: 코드임을 명시
                        "lang": guess_lang(ch),          # ★ 간단 언어 추정
                    }
                })

    # 저장
    with open(CHUNKS_OUT, "w", encoding="utf-8") as f:
        for r in chunks:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 요약 출력
    text_cnt = sum(1 for r in chunks if not r["metadata"].get("is_code"))
    code_cnt = len(chunks) - text_cnt
    print(f"✅ chunks saved: {CHUNKS_OUT} ({len(chunks)} rows, text={text_cnt}, code={code_cnt})")

if __name__ == "__main__":
    main()
