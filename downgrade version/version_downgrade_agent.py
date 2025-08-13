"""
Version Downgrade Agent
=======================

신(eGovFrame 4.x 등) Java 코드를 다중 타겟 구버전(예: 2.7.1, 3.9.0 등)으로
다운그레이드합니다.

- FAISS(vector_store/version_vector_store)에서 유사 예제를 검색
- LLM(ChatOpenAI)으로 타겟 버전별 변환
- 결과/요약 리포트 + IR(JSON) 빌드 유틸 제공

필수:
1) OPENAI_API_KEY (.env 또는 환경변수)
2) vector_store/version_vector_store/ (embed_version_documents_downgrade.py 등으로 생성)
3) docs/prompt_version_downgrade.txt ({{input_code}}, {{reference}}, {{target_version}})
"""

from __future__ import annotations

from typing import TypedDict, List, Dict
from pathlib import Path
from datetime import datetime
import os
import json
import re

from dotenv import load_dotenv

# 권장 import (Deprecation 경고 방지)
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS

load_dotenv()


class DowngradeState(TypedDict):
    input_code: str
    target_versions: List[str]
    retrieved: List[str]
    results: Dict[str, str]      # {version: code}
    report: Dict[str, str]
    output_dir: str              # 저장 폴더 (예: "converted")
    input_filename: str          # 입력 파일명(경로 포함 가능)


# -------- 내부 유틸 --------
def _require_env() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY가 설정되지 않았습니다. .env 또는 환경 변수로 설정해 주세요."
        )

def _require_path(p: Path, msg: str) -> None:
    if not p.exists():
        raise FileNotFoundError(msg)

def _derive_basename(state: DowngradeState) -> str:
    # 파일명이 있으면 파일명 기반, 없으면 class 명, 둘 다 없으면 기본값
    if state.get("input_filename"):
        return os.path.splitext(os.path.basename(state["input_filename"]))[0]
    m = re.search(r"\bclass\s+([A-Za-z_]\w*)", state["input_code"])
    return m.group(1) if m else "Converted"


# -------- 핵심 단계 --------
def retrieve_examples(
    state: DowngradeState,
    store_dir: str | Path = "vector_store/version_vector_store",
    k: int = 3,
) -> DowngradeState:
    """FAISS에서 입력 코드와 유사한 예제 k개 검색."""
    store_path = Path(store_dir)
    _require_path(store_path, f"벡터스토어가 없습니다: {store_path}")

    embedding = OpenAIEmbeddings(model="text-embedding-3-small")
    vectordb = FAISS.load_local(
        str(store_path),
        embedding,
        allow_dangerous_deserialization=True,
    )
    docs = vectordb.similarity_search(state["input_code"], k=k)
    state["retrieved"] = [d.page_content for d in docs]
    return state


def convert_code(
    state: DowngradeState,
    template_path: str | Path = "docs/prompt_version_downgrade.txt",
) -> DowngradeState:
    """타겟 버전별로 프롬프트를 채워 LLM으로 다운그레이드 코드를 생성."""
    _require_env()

    tpath = Path(template_path)
    _require_path(tpath, f"다운그레이드 프롬프트 템플릿이 없습니다: {tpath}")

    template = tpath.read_text(encoding="utf-8")
    llm = ChatOpenAI(model="gpt-4o-mini")

    results: Dict[str, str] = {}
    reference = "\n\n---\n\n".join(state.get("retrieved", []))
    for version in state["target_versions"]:
        prompt = (
            template.replace("{{input_code}}", state["input_code"])
                    .replace("{{reference}}", reference)
                    .replace("{{target_version}}", version)
        )
        ai_msg = llm.invoke(prompt)  # predict() 대신 invoke()
        results[version] = (ai_msg.content or "").strip()

    state["results"] = results
    return state


def finalize(state: DowngradeState) -> DowngradeState:
    """간단 리포트 채우기."""
    state["report"] = {
        "target_versions": ", ".join(state.get("target_versions", [])),
        "retrieved_count": str(len(state.get("retrieved", []))),
        "generated_versions": str(len(state.get("results", {}))),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    return state


def save_outputs(state: DowngradeState) -> DowngradeState:
    """버전별 하위 폴더에 코드 저장 (선택적, 그래프에서 사용 가능)."""
    out_dir = state.get("output_dir") or "converted"
    os.makedirs(out_dir, exist_ok=True)
    base = _derive_basename(state)
    for ver, code in state.get("results", {}).items():
        ver_dir = os.path.join(out_dir, ver)
        os.makedirs(ver_dir, exist_ok=True)
        out_path = os.path.join(ver_dir, f"{base}_{ver}.java")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(code)
    return state


# -------- IR(JSON) --------
def build_ir(state: DowngradeState) -> dict:
    """
    다운그레이드 컨텍스트 IR(JSON).
    업그레이드와 맞춰: meta/inputs/retrieval/outputs/audit
    outputs.results는 {version: code}
    """
    return {
        "meta": {
            "ir_version": "1.0",
            "pipeline": "egovframe_downgrade",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "source_language": "java",
            "source_framework": "egovframe",
            "target_framework": "egovframe-legacy",
            "target_versions": state.get("target_versions", []),
        },
        "inputs": {
            "input_code": state.get("input_code", ""),
            "input_filename": state.get("input_filename", ""),
        },
        "retrieval": [
            {"index": i, "snippet": s}
            for i, s in enumerate(state.get("retrieved", []), start=1)
        ],
        "outputs": {
            "results": state.get("results", {}),   # {version: code}
            "report": state.get("report", {}),
        },
        "audit": [
            {"step": "retrieve_examples", "ok": True},
            {"step": "convert_code", "ok": bool(state.get("results", {}))},
            {"step": "finalize", "ok": True},
        ],
    }


def dump_ir_to_file(ir: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(ir, ensure_ascii=False, indent=2), encoding="utf-8")
