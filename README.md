# ai

메인 에이전트 설명
 
패키지 단위로 실행(그래서 import를 좀 변경 했습니다):python -m translate.app.orchestrator   다른 각각의 에이전트 체크시   python -m translate.app.egov_agent 이런식으로 하시면 각각 툴 에이전트 확인 가능하실겁니다 

orchestrator.py 가 메인 에이전트

from translate.app.agent_analyze_test import AnalysisTestAgent
from translate.app.python_agent import run_python_agent
from translate.app.egov_agent import run_egov_agent  

위의 3가지 툴을 사용

카프카의 경우 정확히 어떻게 설계 되고 있는지 모르겠지만 

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

이 3가지 함수에 카프카 설정을 하면 좋을거 같습니다 지금 리턴을 바로 에이전트에 주는 방식인데

def py_to_java(outdir: str) -> Dict[str, Any]:
    result=run_python_agent(limit=2)
    return  result  

이런식으로 하면 각각 최종 스테이트 확인 가능합니다.
