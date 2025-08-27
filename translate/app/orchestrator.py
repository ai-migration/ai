# orchestrator.py
import json, tempfile, shutil, os
from typing import Dict, Any
from langchain.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate

import os, tempfile

# --- 에이전트 ---
from translate.app.analyze_agent import AnalysisAgent
from translate.app.python_agent import run_python_agent
from translate.app.egov_agent import ConversionEgovAgent
from translate.app.producer import MessageProducer
from translate.app.utils import _is_s3_uri, _is_http_uri, _download_s3_to, _download_http_to

SYSTEM = "너는 코드 마이그레이션 수퍼바이저다. 목표를 달성할 때까지 적절한 도구를 순차적으로 호출하라."
HUMAN = """
목표: {goal}

현재 상태(state):
{state}

규칙:
- 중요!! 제일 먼저 run_analysis를 통해 집파일을 열어 분석할 코드본을 만들어주세요!!
- 당신의 테스크는 위에서 나온 코드에서 state.language 각각의 변환을 통해 최종적으로 egov 표준프레임워크로 변환하는것입니다 명심해 주세요!

필요한 도구를 골라 한 번에 하나씩 호출하라.
완료 시 더는 도구를 호출하지 말고 JSON으로 status만 알려라.
"""

producer = MessageProducer()

def run_analysis(user_id, job_id, input_path: str, extract_dir: str) -> Dict[str, Any]:
    summary = {"language": "unknown", "converted": False}
    try:
        producer.send_message(topic='agent-res', 
                              message={'userId': user_id, 'jobId': job_id, 'description': '프로젝트 구조 분석을 시작합니다.'},
                              headers=[('AGENT', 'ANALYSIS')])
        
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
                              message={'userId': user_id, 'jobId': job_id, 'language': summary['language'], 'status': status, 'description': description},
                              headers=[('AGENT', 'ANALYSIS')])
    return summary

def py_to_java(user_id, job_id) -> Dict[str, Any]:
    try:
        producer.send_message(topic='agent-res', 
                              message={'userId': user_id, 'jobId': job_id, 'description': '언어 변환을 시작합니다.'},
                              headers=[('AGENT', 'PYTHON')])
        
        run_python_agent(limit=2)
        status = 'SUCCESS'
        description = '파이썬을 자바로 변환 완료되었습니다.'
    except Exception as e:
        print(e)
        status = 'FAIL'
        description = '파이썬을 자바로 변환 실패되었습니다.'
    finally:
        producer.send_message(topic='agent-res', 
                              message={'userId': user_id, 'jobId': job_id, 'status': status, 'description': description},
                              headers=[('AGENT', 'PYTHON')])

def java_to_egov(user_id, job_id) -> Dict[str, Any]:
    try:
        producer.send_message(topic='agent-res', 
                              message={'userId': user_id, 'jobId': job_id, 'description': '전자정부표준프레임워크 변환을 시작합니다.'},
                              headers=[('AGENT', 'EGOV')])
        
        egov_agent = ConversionEgovAgent()
        graph = egov_agent.build_graph()
        state = egov_agent.init_state(user_id, job_id)
        final_state = graph.invoke(state, config={"recursion_limit": 1000})
        
        # with open("output/conversion_result.json", 'w', encoding='utf-8') as f:
        #     json.dump(final_state, f, ensure_ascii=False, indent=2)
        
        status = 'SUCCESS'
        description = '전자정부표준프레임워크 변환 완료되었습니다.'
        result = final_state
        if os.path.exists('output'):
            shutil.rmtree('output')
            print(f"중간 산출물을 삭제했습니다.")
    except Exception as e:
        print(e)
        status = 'FAIL'
        description = '전자정부표준프레임워크 변환 실패되었습니다.'
        result = {}
    finally:
        producer.send_message(topic='agent-res', 
                              message={'userId': user_id, 'jobId': job_id, 'status': status, 'description': description, 'result': result},
                              headers=[('AGENT', 'EGOV')])
        

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

        self.tools = [self.run_analysis_tool, self.py_to_java_tool, self.java_to_egov_tool]
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0)
        self.prompt = ChatPromptTemplate.from_messages([("system", SYSTEM), ("human", HUMAN), ("placeholder","{agent_scratchpad}")])
        self.agent = create_tool_calling_agent(self.llm, self.tools, self.prompt)
        self.executor = AgentExecutor(agent=self.agent, tools=self.tools, verbose=True)
        
    def run(self, user_id, job_id, input_path):
        outdir = f"output/"
        with tempfile.TemporaryDirectory() as tmp:
            download_dir = os.path.join(tmp, "downloads")   # ZIP 저장
            extract_dir  = os.path.join(tmp, "extracted")   # 압축 풀 위치(이것만 삭제)
            os.makedirs(download_dir, exist_ok=True)
            os.makedirs(extract_dir,  exist_ok=True)

            # 원격 ZIP은 반드시 download_dir에 저장
            if _is_s3_uri(input_path):
                local_input = _download_s3_to(download_dir, input_path)
            elif _is_http_uri(input_path):
                local_input = _download_http_to(download_dir, input_path)
            else:
                local_input = input_path  # 로컬이면 그대로(단, extract_dir 안은 금지)

            # 안전장치 + 디버그
            print(f"[ORCH] __file__={__file__}")
            print(f"[DEBUG] local_input={local_input}")
            print(f"[DEBUG] extract_dir={extract_dir}")
            assert os.path.isfile(local_input)

            init_state = json.dumps({
                "user_id": user_id,
                "job_id": job_id,
                "input_path": local_input,
                "extract_dir": extract_dir,
                "outdir": outdir,
                "language": "unknown"
            })
            print("[ORCH] init_state:", init_state)
            result = self.executor.invoke({
                "goal": "파이썬/자바 코드를 eGov 표준 구조로 자동 변환",
                "state": init_state
            })
        return result

if __name__ == "__main__":  
    # r = run_analysis(1, 1, r"C:\Users\User\Desktop\dev\project\0811test.zip", './res')
    conv_agent = ConversionAgent()
    conv_agent.run(1, 1, r"C:\Users\User\Downloads\python_project.zip")