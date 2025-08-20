import os, json, re, time, argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Optional: OpenAI + tokenizer
from openai import OpenAI
try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
except Exception:
    _enc = None

import chromadb

# =====================
# Path resolution
# =====================
APP_DIR  = Path(__file__).resolve().parent          # ...\ai\security\app
PROJ_DIR = APP_DIR.parent                           # ...\ai\security

CANDIDATES = [
    APP_DIR  / "outputs" / "security_guides.jsonl",   # ← your current file location (highest priority)
    PROJ_DIR / "outputs" / "security_guides.jsonl",
    APP_DIR  / "data"    / "security_guides.jsonl",
    PROJ_DIR / "data"    / "security_guides.jsonl",
    Path.cwd() / "security_guides.jsonl",
]

PERSIST_DIR = str((APP_DIR / "index").resolve())   # where chroma.sqlite3 will be stored
COLLECTION_NAME = "security_guides"
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-large")

# =====================
# IO helpers
# =====================
def resolve_data_path(cli_path: Optional[str]) -> Path:
    if cli_path:
        p = Path(cli_path).resolve()
        if not p.exists():
            raise FileNotFoundError(str(p))
        return p
    for p in CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        "security_guides.jsonl not found.\n" + "\n".join(f"- {str(p)}" for p in CANDIDATES)
    )

def load_jsonl(p: Path):
    # utf-8-sig handles BOM if present
    with open(p, "r", encoding="utf-8-sig") as f:
        for i, line in enumerate(f):
            line=line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as e:
                print(f"⚠️  JSON decode failed at line {i}: {e}")

# =====================
# Tokenization & chunking
# =====================
def tokenize(text: str) -> List[int]:
    if _enc is None:
        return [ord(c) for c in text]
    return _enc.encode(text)

def detokenize(ids: List[int]) -> str:
    if _enc is None:
        return "".join(chr(i) for i in ids)
    return _enc.decode(ids)

def chunk_by_tokens(text: str, max_tokens: int, overlap: int, *, min_chars: int = 20) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    ids = tokenize(text)
    chunks=[]
    step=max(1, max_tokens - overlap)
    for i in range(0, len(ids), step):
        window = ids[i:i+max_tokens]
        if not window:
            break
        chunk = detokenize(window).strip()
        if len(chunk) >= min_chars:   # ← 최소 길이
            chunks.append(chunk)
        if i + max_tokens >= len(ids):
            break
    return chunks

# =====================
# Utils
# =====================
# === utils for sections-aware extraction ===
def norm_key(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9가-힣]", "", s)
    return s

def stringify(v: Any) -> str:
    if v is None: return ""
    if isinstance(v, str): return v
    if isinstance(v, (int, float)): return str(v)
    if isinstance(v, list): return "\n".join(stringify(x) for x in v if x)
    if isinstance(v, dict):
        for k in ["content","text","value","body","desc","description","code","snippet"]:
            if k in v and v[k]:
                return stringify(v[k])
        return "\n".join(stringify(x) for x in v.values() if x)
    return ""

OV_KEYS   = {"개요","요약","설명","overview","summary","description"}
MIT_KEYS  = {"보안대책","대책","대응","가이드","조치","mitigation","countermeasure","guideline","measures","remediation","prevention","controls"}
REF_KEYS  = {"참고자료","참고","레퍼런스","링크","references","reference","refs","sources","links","documents"}
WEAK_KEYS = {"취약","취약코드","취약예시","취약예시코드","unsafe","vulnerable","weak","bad","insecure","badexample"}
SAFE_KEYS = {"안전","안전코드","안전예시","안전예시코드","safe","secure","fixed","good","hardened","goodexample"}

OV_N = {norm_key(k) for k in OV_KEYS}
MI_N = {norm_key(k) for k in MIT_KEYS}
RE_N = {norm_key(k) for k in REF_KEYS}
WK_N = {norm_key(k) for k in WEAK_KEYS}
SF_N = {norm_key(k) for k in SAFE_KEYS}

def extract_from_sections(sections: Any):
    """Return overview, mitigation, references, weak_code, safe_code, debug_info"""
    ov_list, mi_list, re_list, wk_list, sf_list = [], [], [], [], []
    dbg = {"type": type(sections).__name__}

    def classify(name: str, value: Any):
        key = norm_key(name)
        text = stringify(value)
        if not text: return
        if key in OV_N:    ov_list.append(text)
        elif key in MI_N:  mi_list.append(text)
        elif key in RE_N:  re_list.append(text)
        elif key in WK_N:  wk_list.append(text)
        elif key in SF_N:  sf_list.append(text)
        else:
            if isinstance(value, dict):
                # nested examples dict
                def pick_first(d, keys):
                    for k in keys:
                        if k in d and d[k]: return stringify(d[k])
                    return ""
                w = pick_first(value, list(WEAK_KEYS))
                s = pick_first(value, list(SAFE_KEYS))
                if w: wk_list.append(w)
                if s: sf_list.append(s)

    if isinstance(sections, dict):
        dbg["keys"] = list(sections.keys())
        for k, v in sections.items():
            classify(k, v)
    elif isinstance(sections, list):
        titles = []
        for it in sections:
            if isinstance(it, dict):
                name = it.get("name") or it.get("title") or it.get("section") or ""
                titles.append(name)
                content = (it.get("content") or it.get("text") or it.get("value")
                           or it.get("body") or it.get("desc") or it.get("description") or it)
                classify(name, content)
                ex = it.get("examples") or it.get("example") or it.get("codes") or it.get("code")
                if isinstance(ex, dict):
                    # try nested weak/safe inside examples
                    def pick_first(d, keys):
                        for k in keys:
                            if k in d and d[k]: return stringify(d[k])
                        return ""
                    w = pick_first(ex, list(WEAK_KEYS))
                    s = pick_first(ex, list(SAFE_KEYS))
                    if w: wk_list.append(w)
                    if s: sf_list.append(s)
        dbg["titles"] = titles
    else:
        s = stringify(sections)
        if s: ov_list.append(s)

    def uniq_join(lst):
        seen=set(); out=[]
        for x in lst:
            x=x.strip()
            if not x or x in seen: continue
            seen.add(x); out.append(x)
        return "\n".join(out)

    return uniq_join(ov_list), uniq_join(mi_list), uniq_join(re_list), uniq_join(wk_list), uniq_join(sf_list), dbg


def pick_first(d: Dict[str, Any], keys: List[str]) -> str:
    for k in keys:
        if k in d and d[k]:
            v = d[k]
            if isinstance(v, list):
                return "\n".join(str(x) for x in v if x)
            if isinstance(v, (str, int, float)):
                return str(v)
    return ""

# fallback extractors (top-level)
def extract_overview_top(r: Dict[str, Any]) -> str:
    return pick_first(r, list(OV_KEYS))

def extract_mitigation_top(r: Dict[str, Any]) -> str:
    return pick_first(r, list(MIT_KEYS))

def extract_references_top(r: Dict[str, Any]) -> str:
    return pick_first(r, list(REF_KEYS))

def extract_code_pair_top(r: Dict[str, Any]) -> Tuple[str,str]:
    code_dict = None
    for key in ["예시코드","코드예시","예시코드(취약/안전)","code_examples","examples"]:
        v = r.get(key)
        if isinstance(v, dict) and v:
            code_dict = v
            break
    weak = ""; safe = ""
    if code_dict:
        weak = pick_first(code_dict, list(WEAK_KEYS))
        safe = pick_first(code_dict, list(SAFE_KEYS))
    if not weak:
        weak = pick_first(r, list(WEAK_KEYS))
    if not safe:
        safe = pick_first(r, list(SAFE_KEYS))
    return weak, safe

# sections-aware extractor
def extract_from_sections(sections: Any) -> Tuple[str,str,str,str,str, Dict[str,Any]]:
    """Return overview, mitigation, references, weak_code, safe_code, debug_info"""
    ov_list: List[str] = []
    mi_list: List[str] = []
    re_list: List[str] = []
    wk_list: List[str] = []
    sf_list: List[str] = []
    dbg: Dict[str, Any] = {"type": type(sections).__name__}

    def classify(name: str, value: Any):
        key = norm_key(name)
        text = stringify(value)
        if not text:
            return
        if key in OV_N:
            ov_list.append(text)
        elif key in MI_N:
            mi_list.append(text)
        elif key in RE_N:
            re_list.append(text)
        elif key in WK_N:
            wk_list.append(text)
        elif key in SF_N:
            sf_list.append(text)
        else:
            # look for nested example dicts
            if isinstance(value, dict):
                w = pick_first(value, list(WEAK_KEYS))
                s = pick_first(value, list(SAFE_KEYS))
                if w: wk_list.append(w)
                if s: sf_list.append(s)

    if isinstance(sections, dict):
        dbg["keys"] = list(sections.keys())
        for k, v in sections.items():
            classify(k, v)
    elif isinstance(sections, list):
        titles = []
        for it in sections:
            if isinstance(it, dict):
                name = it.get("name") or it.get("title") or it.get("section") or ""
                titles.append(name)
                content = (
                    it.get("content") or it.get("text") or it.get("value")
                    or it.get("body") or it.get("desc") or it.get("description") or it
                )
                classify(name, content)
                # also probe nested code examples
                ex = it.get("examples") or it.get("example") or it.get("codes")
                if isinstance(ex, dict):
                    w = pick_first(ex, list(WEAK_KEYS))
                    s = pick_first(ex, list(SAFE_KEYS))
                    if w: wk_list.append(w)
                    if s: sf_list.append(s)
        dbg["titles"] = titles
    else:
        # unknown structure; just stringify
        s = stringify(sections)
        if s:
            ov_list.append(s)

    def uniq_join(lst: List[str]) -> str:
        seen = set(); out = []
        for x in lst:
            if not x: continue
            k = x.strip()
            if k in seen: continue
            seen.add(k); out.append(k)
        return "\n".join(out)

    return uniq_join(ov_list), uniq_join(mi_list), uniq_join(re_list), uniq_join(wk_list), uniq_join(sf_list), dbg

# =====================
# Language guess for code
# =====================
def guess_lang_from_code(code: str) -> str:
    t = (code or "").strip()
    if not t:
        return "txt"
    if re.search(r"\bimport\s+\w+|def\s+\w+\(", t):
        return "python"
    if re.search(r"\bpublic\s+class\b|\bSystem\.out\.println\b", t):
        return "java"
    if re.search(r"#include\s*<\w+>|int\s+main\s*\(", t):
        return "c"
    if re.search(r"function\s+\w+\(|console\.log", t):
        return "javascript"
    if re.search(r"SELECT\s+.+\s+FROM\b", t, re.IGNORECASE):
        return "sql"
    return "txt"

# =====================
# Embedding
# =====================
_client: Optional[OpenAI] = None
def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client

def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    client = get_client()
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]

# =====================
# Main
# =====================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inpath", default=None, help="path to security_guides.jsonl")
    args = ap.parse_args()

    data_path = resolve_data_path(args.inpath)
    print(f"📦 load: {data_path}")
    rows = list(load_jsonl(data_path))
    print(f"→ {len(rows)} guides")

    chroma = chromadb.PersistentClient(path=PERSIST_DIR)
    col = chroma.get_or_create_collection(COLLECTION_NAME, metadata={"hnsw:space":"cosine"})

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []

    TXT_MAX, TXT_OV = 480, 64
    CODE_MAX, CODE_OV = 1000, 100

    empty_guides = []
    total_txt_chunks = 0
    total_code_chunks = 0

    for idx, r in enumerate(rows):
        parent_id = str(
            r.get("security_name") or r.get("ssecurity_name") or r.get("보안명")
            or r.get("name") or r.get("title") or r.get("security_id") or f"guide_{idx}"
        )

        overview = mitigation = references = weak = safe = ""
        dbg_sections = None
        if "sections" in r and r["sections"]:
            overview, mitigation, references, weak, safe, dbg_sections = extract_from_sections(r["sections"])
        else:
            # 기존 top-level 키 탐색 (fallback)
            overview   = extract_overview(r)
            mitigation = extract_mitigation(r)
            references = extract_references(r)
            weak, safe = extract_code_pair(r)


        per_guide_chunks = 0

        # Text sections
        for section, text in [("개요", overview), ("보안대책", mitigation), ("참고자료", references)]:
            for i, ch in enumerate(chunk_by_tokens(text, TXT_MAX, TXT_OV, min_chars=20)):
                ids.append(f"{parent_id}::TXT::{section}::{i}")
                docs.append(ch)
                metas.append({
                    "parent_id": parent_id,
                    "section": section,
                    "is_code": False,
                    "lang": "txt",
                    "source_section": section,
                })
                per_guide_chunks += 1
                total_txt_chunks += 1

        # Code sections
        for code_section, code in [("예시코드:취약", weak), ("예시코드:안전", safe)]:
            lang = guess_lang_from_code(code)
            for i, ch in enumerate(chunk_by_tokens(code, CODE_MAX, CODE_OV, min_chars=5)):
                ids.append(f"{parent_id}::CODE::{code_section}::{i}")
                docs.append(ch)
                metas.append({
                    "parent_id": parent_id,
                    "section": code_section,
                    "is_code": True,
                    "lang": lang,
                    "source_section": code_section,
                })
                per_guide_chunks += 1
                total_code_chunks += 1

        if per_guide_chunks == 0:
            keys_preview = list(r.keys())
            print(f"⚠️  no chunks for guide[{idx}] parent_id='{parent_id}' keys={keys_preview}")
            if dbg_sections is None and "sections" in r:
                print(f"   sections present but empty/invalid: type={type(r['sections']).__name__}")
            elif dbg_sections is not None:
                print(f"   sections debug: {dbg_sections}")
            print(f"   overview={len(overview)} chars, mitigation={len(mitigation)}, refs={len(references)}, weak={len(weak)}, safe={len(safe)}")
            empty_guides.append(parent_id)

    print(f"🧩 chunks: {len(docs)} (text={total_txt_chunks}, code={total_code_chunks})")

    if not docs:
        print("❌ No chunks produced. Check your JSONL structure under 'sections' (see per-guide debug).")
        return

    # Embed & index
    embs: List[List[float]] = []
    B = 64
    for i in range(0, len(docs), B):
        batch = docs[i:i+B]
        embs.extend(embed_texts(batch))
        time.sleep(0.02)

    print("🗃 add to Chroma …")
    col.add(ids=ids, documents=docs, metadatas=metas, embeddings=embs)
    print(f"✅ indexed: {len(ids)} docs into '{COLLECTION_NAME}' at {PERSIST_DIR}")
    if empty_guides:
        print(f"ℹ️  {len(empty_guides)} guides produced 0 chunks (skipped): {', '.join(empty_guides[:5])}{' ...' if len(empty_guides)>5 else ''}")

if __name__ == "__main__":
    main()
