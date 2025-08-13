# supervisor_agent.py
import json, tempfile, shutil, os
from typing import Dict, Any
from langchain.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate

# --- 에이전트 ---
from translate.app.analyze_agent import AnalysisAgent
from translate.app.python_agent import run_python_agent
from translate.app.egov_agent import run_egov_agent  # 위에서 만든 함수

from translate.app.producer import MessageProducer

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

producer = MessageProducer()

def run_analysis(user_id, job_id, input_path: str, extract_dir: str) -> Dict[str, Any]:
    try:
        graph = AnalysisAgent().build_graph()
        state = {"input_path": input_path, "extract_dir": extract_dir}
        final_state = graph.invoke(state)
        summary = {
            "language": final_state.get("language"),
            "converted": bool(final_state.get("classes")) or bool(final_state.get("controller_code"))
        }
        status = 'SUCCESS'
        description = '프로젝트 구조 분석이 완료되었습니다.'
    except Exception as e:
        print(e)
        status = 'FAIL'
        description = '프로젝트 구조 분석이 실패되었습니다.'
    finally:
        producer.send_message(topic='agent-res', 
                              message={'userId': user_id, 'job_id': job_id, 'language': summary['language'], 'status': status, 'description': description},
                              headers=[('AGENT', 'ANALYSIS')])
    return summary

def py_to_java(user_id, job_id) -> Dict[str, Any]:
    try:
        run_python_agent(limit=2)
        status = 'SUCCESS'
        description = '파이썬을 자바로 변환 완료되었습니다.'
    except Exception as e:
        print(e)
        status = 'FAIL'
        description = '파이썬을 자바로 변환 실패되었습니다.'
    finally:
        producer.send_message(topic='agent-res', 
                              message={'userId': user_id, 'job_id': job_id, 'status': status, 'description': description},
                              headers=[('AGENT', 'PYTHON')])

def java_to_egov(user_id, job_id) -> Dict[str, Any]:
    try:
        result = run_egov_agent()
        with open("output/conversion_result.json", 'w', encoding='utf-8') as f:
            json.dump(result.tasks_output[-1].pydantic.model_dump(), f, ensure_ascii=False, indent=2)
        status = 'SUCCESS'
        description = '전자정부표준프레임워크 변환 완료되었습니다.'
    except Exception as e:
        print(e)
        status = 'FAIL'
        description = '전자정부표준프레임워크 변환 실패되었습니다.'
    finally:
        producer.send_message(topic='agent-res', 
                              message={'userId': user_id, 'job_id': job_id, 'status': status, 'description': description},
                              headers=[('AGENT', 'EGOV')])
        
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

class ConversionAgent:
    def __init__(self):
        self.run_analysis_tool     = StructuredTool.from_function(name="run_analysis",     
                                                                  func=lambda user_id, job_id, input_path, extract_dir: run_analysis(user_id, job_id, input_path, extract_dir), 
                                                                  description="ZIP을 분석해 언어/구조를 탐지")
        self.py_to_java_tool       = StructuredTool.from_function(name="py_to_java",       
                                                                  func=lambda user_id, job_id: py_to_java(user_id, job_id), 
                                                                  description="Python 분석 결과(JSONL)를 기반으로 Java 코드 생성")
        self.java_to_egov_tool     = StructuredTool.from_function(name="java_to_egov",     
                                                                  func=lambda user_id, job_id: java_to_egov(user_id, job_id), 
                                                                  description="기존 Java를 eGov 스타일로 변환")
        self.validate_fix_tool     = StructuredTool.from_function(name="validate_fix",     
                                                                  func=lambda outdir: validate_fix(outdir), 
                                                                  description="eGov 디렉토리 필수 트리/스켈레톤 보정")
        self.package_publish_tool  = StructuredTool.from_function(name="package_publish",  
                                                                  func=lambda outdir: package_publish(outdir), 
                                                                  description="결과물 zip 생성 후 완료 상태 반환")
        self.tools = [self.run_analysis_tool, self.py_to_java_tool, self.java_to_egov_tool, self.validate_fix_tool, self.package_publish_tool]
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0)
        self.prompt = ChatPromptTemplate.from_messages([("system", SYSTEM), ("human", HUMAN), ("placeholder","{agent_scratchpad}")])
        self.agent = create_tool_calling_agent(self.llm, self.tools, self.prompt)
        self.executor = AgentExecutor(agent=self.agent, tools=self.tools, verbose=True)
        
    def run(self, user_id, job_id, input_path):
        outdir = f"{user_id}/{job_id}/conversed/"
        with tempfile.TemporaryDirectory() as tmp:
            init_state = json.dumps({"user_id": user_id, "job_id": job_id, "input_path": input_path, "extract_dir": tmp, "outdir": outdir, "language": "unknown"}, ensure_ascii=False)
            result = self.executor.invoke({"goal": "파이썬/자바 코드를 eGov 표준 구조로 자동 변환", "state": init_state})
        
        return result

if __name__ == "__main__":  
    # r = run_analysis(1, 1, r"C:\Users\User\Desktop\dev\project\0811test.zip", './res')
    conv_agent = ConversionAgent()
    conv_agent.run(1, 1, r"C:\Users\User\Desktop\dev\project\0811test.zip")