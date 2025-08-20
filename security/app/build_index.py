# build_index.py — security_guides.json(.jsonl) → OpenAI 임베딩 → Qdrant(local)
import os, json, uuid
from pathlib import Path
from typing import List, Dict, Any
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
DATA_JSON  = Path(os.getenv("DATA_JSON",  DATA_DIR / "security_guides.json"))
DATA_JSONL = Path(os.getenv("DATA_JSONL", DATA_DIR / "security_guides.jsonl"))

DB_DIR = BASE / "qdrant_local"
DB_DIR.mkdir(parents=True, exist_ok=True)

COLLECTION  = os.getenv("COLLECTION", "security_guides_oai3")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-large")  # 비용↓: ...-small
BATCH = int(os.getenv("BATCH", "16"))

def _parse_json_or_jsonl_str(s: str):
    try:
        obj = json.loads(s)
        if isinstance(obj, list): return obj
        raise ValueError("not list")
    except Exception:
        items=[]
        for line in s.splitlines():
            line=line.strip()
            if line: items.append(json.loads(line))
        return items

def load_guides() -> List[Dict[str, Any]]:
    if DATA_JSON.exists():
        raw = DATA_JSON.read_text(encoding="utf-8")
        try:
            data = _parse_json_or_jsonl_str(raw)
            if raw.lstrip().startswith("{"):
                DATA_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return data
        except Exception:
            pass
    if DATA_JSONL.exists():
        data = _parse_json_or_jsonl_str(DATA_JSONL.read_text(encoding="utf-8"))
        DATA_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data
    raise FileNotFoundError("security_guides.json(.jsonl) 없음")

def mk_docs(g: Dict[str, Any]):
    sid = g["security_id"]
    sname = g.get("security_name", sid)
    secs = g.get("sections", {}) or {}
    docs=[]
    for sec in ["overview","mitigation","unsafe_examples","safe_examples","references"]:
        t = (secs.get(sec) or "").strip()
        if not t: continue
        docs.append({
            "id_str": f"{sid}#{sec}",     # 문자열 id(결정적 UUID로 변환)
            "text": t,
            "payload": {
                "security_id": sid, "security_name": sname, "section": sec,
                "text": t[:4000]   # 스니펫용(너무 길면 잘라 저장)
            }
        })
    return docs

def embed_batch(oai: OpenAI, texts: List[str]) -> List[List[float]]:
    return [d.embedding for d in oai.embeddings.create(model=EMBED_MODEL, input=texts).data]

def main():
    guides = load_guides()
    docs=[]
    for g in guides: docs += mk_docs(g)
    print(f"📦 guides: {len(guides)} | chunks: {len(docs)} (batch={BATCH})")

    oai = OpenAI()
    # 정확한 차원 계산
    dim = len(embed_batch(oai, [docs[0]["text"]])[0])

    qdr = QdrantClient(path=str(DB_DIR))  # 로컬 모드
    # 컬렉션 재생성
    if any(c.name == COLLECTION for c in qdr.get_collections().collections):
        qdr.delete_collection(COLLECTION)
    qdr.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
    )
    print(f"🗂  collection ready: {COLLECTION} @ {DB_DIR} (dim={dim})")

    # 업서트
    for i in range(0, len(docs), BATCH):
        chunk = docs[i:i+BATCH]
        vectors = embed_batch(oai, [d["text"] for d in chunk])
        points = []
        for d, v in zip(chunk, vectors):
            # 문자열 id → 결정적 UUID v5 생성 후 **문자열로** 전달
            pid = uuid.uuid5(uuid.NAMESPACE_URL, d["id_str"])
            points.append(PointStruct(id=str(pid), vector=v, payload=d["payload"]))
        qdr.upsert(collection_name=COLLECTION, points=points)
        print(f"→ upsert {i+len(points)}/{len(docs)}")

    print("✅ done.")

if __name__ == "__main__":
    main()
