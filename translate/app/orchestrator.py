# supervisor_agent.py
import json, tempfile, shutil, os
from typing import Dict, Any
from langchain.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate

# --- 1) 기존 그래프/크루를 함수로 감싼 Tool 구현 ---
from translate.app.agent_analyze_test import AnalysisTestAgent
from translate.app.python_agent import run_python_agent
from translate.app.egov_agent import run_egov_agent  # 위에서 만든 함수

def run_analysis(input_path: str, extract_dir: str) -> Dict[str, Any]:
    graph = AnalysisTestAgent().build_graph()
    state = {"input_path": input_path, "extract_dir": extract_dir}
    final_state = graph.invoke(state)
    summary = {
        "language": final_state.get("language"),
        "converted": bool(final_state.get("classes")) or bool(final_state.get("controller_code"))
    }
    return summary

def py_to_java(outdir: str) -> Dict[str, Any]:
    return run_python_agent(limit=2)

def java_to_egov() -> Dict[str, Any]:
    return run_egov_agent()

def validate_fix(outdir: str) -> Dict[str, Any]:
    must = [
        "egovframework/com/cop/bbs/controller",
        "egovframework/com/cop/bbs/service/impl",
        "egovframework/com/cop/bbs/service",
        "egovframework/com/cop/bbs/dao",
        "egovframework/com/cop/bbs/mapper",
        "egovframework/com/cop/bbs/vo",
    ]
    for d in must: os.makedirs(os.path.join(outdir, d), exist_ok=True)
    return {"validated": True}

def package_publish(outdir: str) -> Dict[str, Any]:
    if os.path.exists(f"{outdir}.zip"): os.remove(f"{outdir}.zip")
    shutil.make_archive(outdir, "zip", outdir)
    return {"status": "done", "zip": f"{outdir}.zip"}

run_analysis_tool     = StructuredTool.from_function(name="run_analysis",     func=lambda input_path, extract_dir: run_analysis(input_path, extract_dir), description="ZIP을 분석해 언어/구조를 탐지")
py_to_java_tool       = StructuredTool.from_function(name="py_to_java",       func=lambda outdir: py_to_java(outdir), description="Python 분석 결과(JSONL)를 기반으로 Java 코드 생성")
java_to_egov_tool     = StructuredTool.from_function(name="java_to_egov",     func=lambda input_paths: java_to_egov(), description="기존 Java를 eGov 스타일로 변환")
validate_fix_tool     = StructuredTool.from_function(name="validate_fix",     func=lambda outdir: validate_fix(outdir), description="eGov 디렉토리 필수 트리/스켈레톤 보정")
package_publish_tool  = StructuredTool.from_function(name="package_publish",  func=lambda outdir: package_publish(outdir), description="결과물 zip 생성 후 완료 상태 반환")

TOOLS = [run_analysis_tool, py_to_java_tool,java_to_egov_tool]

# --- 2) 상위 ‘진짜 에이전트’ (도구 선택·의사결정 루프) ---
SYSTEM = "너는 코드 마이그레이션 수퍼바이저다. 목표를 달성할 때까지 적절한 도구를 순차적으로 호출하라."
HUMAN = """
목표: {goal}

현재 상태(state):
{state}

규칙:
- 중요!! 제일 먼저 run_analysis를 통해 집파일을 열어 분석할 코드본을 만들어주세요!!
- state.language가 'python'이면 py_to_java(outdir) → validate_fix(outdir) → package_publish(outdir)
- state.language가 'java'   이면 java_to_egov(input_paths) → validate_fix(outdir) → package_publish(outdir)
- state.language가 'unknown'이면 우선 run_analysis(input_path, extract_dir)을 호출해 언어를 파악
- 각 호출 후 state를 갱신하고, 완료되면 status='done'을 반환

필요한 도구를 골라 한 번에 하나씩 호출하라.
완료 시 더는 도구를 호출하지 말고 JSON으로 status만 알려라.
"""

llm = ChatOpenAI(model="gpt-4o", temperature=0)
prompt = ChatPromptTemplate.from_messages([("system", SYSTEM), ("human", HUMAN), ("placeholder","{agent_scratchpad}")])
agent = create_tool_calling_agent(llm, TOOLS, prompt)
executor = AgentExecutor(agent=agent, tools=TOOLS, verbose=True)

def run_supervisor(input_zip: str, outdir: str = "egov_generated_project") -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        init_state = json.dumps({"input_path": input_zip, "extract_dir": tmp, "outdir": outdir, "language": "unknown"}, ensure_ascii=False)
        result = executor.invoke({"goal": "파이썬/자바 코드를 eGov 표준 구조로 자동 변환", "state": init_state})
        return result
    
    
input_zip_path = r'C:\Users\rngus\ai-migration\ai\test\models.zip'
outdir = 'egov_generated_project'  # 결과 디렉토리명 (선택)

result = run_supervisor(input_zip_path, outdir)

print(result)