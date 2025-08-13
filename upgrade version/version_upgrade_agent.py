"""
Version Upgrade Agent
=====================

구(3.x 등) eGovFrame 기반 Java 코드를 목표 신버전(예: 4.x) 규약에 맞게
업그레이드하는 모듈입니다.

- 유사 예제를 FAISS(vector store)에서 검색하여 프롬프트에 주입
- LLM(ChatOpenAI)으로 업그레이드 코드 생성
- 결과/요약 리포트 + IR(JSON) 빌드 유틸 제공

필수 준비물:
1) OPENAI_API_KEY (.env 또는 환경 변수)
2) version_vector_store/  (embed_version_documents.py 등으로 미리 생성)
3) docs/prompt_version.txt (프롬프트 템플릿; {{input_code}}, {{reference}}, {{target_version}} 사용)
"""

from __future__ import annotations

from typing import TypedDict, List, Dict
from pathlib import Path
from datetime import datetime
import json
import os

from dotenv import load_dotenv

# 권장 import (Deprecation 경고 방지)
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS

load_dotenv()


class UpgradeState(TypedDict):
    input_code: str
    target_version: str
    retrieved: List[str]
    result: str
    report: Dict[str, str]


def _require_path(p: Path, msg: str) -> None:
    if not p.exists():
        raise FileNotFoundError(msg)


def _require_env() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY가 설정되지 않았습니다. .env 또는 환경 변수로 설정해 주세요."
        )


def retrieve_examples(state: UpgradeState, store_dir: str | Path = "version_vector_store",
                      k: int = 3) -> UpgradeState:
    """FAISS 벡터스토어에서 입력 코드와 유사한 예제를 k개 검색."""
    store_path = Path(store_dir)
    _require_path(store_path, "version_vector_store 폴더가 없습니다. 먼저 임베딩을 생성하세요.")

    embedding = OpenAIEmbeddings(model="text-embedding-3-small")
    vectordb = FAISS.load_local(
        str(store_path),
        embedding,
        allow_dangerous_deserialization=True,
    )
    docs = vectordb.similarity_search(state["input_code"], k=k)
    state["retrieved"] = [d.page_content for d in docs]
    return state


def convert_code(state: UpgradeState, template_path: str | Path = "docs/prompt_version.txt") -> UpgradeState:
    """프롬프트 템플릿을 채워 LLM으로 업그레이드 코드를 생성."""
    _require_env()

    tpath = Path(template_path)
    _require_path(tpath, f"업그레이드 프롬프트 템플릿이 없습니다: {tpath}")

    template = tpath.read_text(encoding="utf-8")
    prompt = (
        template.replace("{{input_code}}", state["input_code"])
                .replace("{{reference}}", "\n\n---\n\n".join(state.get("retrieved", [])))
                .replace("{{target_version}}", state["target_version"])
    )

    llm = ChatOpenAI(model="gpt-4o-mini")
    ai_msg = llm.invoke(prompt)  # predict() 대신 invoke()
    state["result"] = (ai_msg.content or "").strip()
    return state


def finalize(state: UpgradeState) -> UpgradeState:
    """간단한 요약 리포트 채우기."""
    state["report"] = {
        "target_version": state["target_version"],
        "retrieved_count": str(len(state.get("retrieved", []))),
        "generated_len": str(len(state.get("result", ""))),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    return state


def build_ir(state: UpgradeState) -> dict:
    """업그레이드 전/후 컨텍스트를 표준 IR(JSON)으로 빌드."""
    return {
        "meta": {
            "ir_version": "1.0",
            "pipeline": "egovframe_upgrade",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "source_language": "java",
            "source_framework": "egovframe-legacy",
            "target_framework": "egovframe",
            "target_version": state["target_version"],
        },
        "inputs": {
            "input_code": state["input_code"],
        },
        "retrieval": [
            {"index": i, "snippet": s}
            for i, s in enumerate(state.get("retrieved", []), start=1)
        ],
        "outputs": {
            "upgraded_code": state.get("result", ""),
            "report": state.get("report", {}),
        },
        "audit": [
            {"step": "retrieve_examples", "ok": True},
            {"step": "convert_code", "ok": bool(state.get("result", "").strip())},
            {"step": "finalize", "ok": True},
        ],
    }


def dump_ir_to_file(ir: dict, path: str | Path) -> None:
    """IR(JSON)을 파일로 저장."""
    Path(path).write_text(json.dumps(ir, ensure_ascii=False, indent=2), encoding="utf-8")
