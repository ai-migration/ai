from crewai import Agent, Task, Crew, LLM
from pydantic import BaseModel
from typing import Dict, Any

from translate.app.egov_tools import CheckCompletedTool, ConversionTool, ProduceTool, State
import os, json

os.environ['OPENAI_API_KEY'] = ''

produce = ProduceTool()
eval = CheckCompletedTool()
conversion_loop = ConversionTool(evaluator=eval)

egov_conv_agent = Agent(
    role="Egov Converter",
    goal="분석 단계에서 생성된 보고서를 바탕으로 전자정부프레임워크(eGovFrame) 스타일에 맞춰 Controller, Service, ServiceImpl, VO 코드를 변환하고, 변환 결과를 보고서와 함께 제공한다.",
    backstory=(
        "나는 수많은 프로젝트를 전자정부프레임워크 표준에 맞게 변환해온 숙련된 변환 전문가다. "
        "분석팀이 넘겨준 코드 구조와 예제 코드를 바탕으로, "
        "각 계층별 규칙과 모범 사례를 철저히 준수하며 코드를 변환한다. "
        "Controller부터 VO까지 모든 계층이 일관된 구조와 품질을 유지하도록 하고, "
        "변환 과정에서 생성된 보고서를 통해 다른 개발자들이 변경 내용을 쉽게 이해할 수 있도록 돕는다."
    ),
    tools=[conversion_loop, produce],
    memory=False,
    verbose=True,
    llm=LLM(model="gpt-4o", temperature=0, api_key=os.environ['OPENAI_API_KEY'])
)

conversion_task = Task(
    description=(
        "입력된 state의 내용:\n"
        "{state}\n\n"
        "orchestrate_loop(state=state)만 정확히 한 번 호출하고, "
        "반환된 최신 state(dict)만 출력하라."
    ),
    agent=egov_conv_agent,
    tools=[conversion_loop],
    input_variables=["state"],
    output_pydantic=State,
    expected_output="최종 state(dict)"
)

# response_task = Task(
#     description=(
#         "이전 단계의 최종 state를 Kafka에 발행하라. "
#         "produce_to_kafka 도구를 사용한다. "),
#     agent=egov_conv_agent,
#     tools=[produce],
#     context=[conversion_task],
#     expected_output="최종 분석 결과를 kafka로 메세지 발행"
# )

egov_crew = Crew(
    agents=[egov_conv_agent],
    tasks=[conversion_task],
    verbose=True, memory=False
)

def init_state(path):
    '''
    [
        {
            "board": {
                "controller": [
                    "code",
                ],
                "service": [
                    "code",
                ]
            }
        }
    ]
    '''
    state = {
                'controller': [],
                'service': [],
                'serviceimpl': [],  
                'vo': [],

                'controller_egov': [],
                'service_egov': [],
                'serviceimpl_egov': [],
                'vo_egov': [],

                'controller_report': {},
                'service_report': {},
                'serviceimpl_report': {},
                'vo_report': {},
                'retrieved': [],
                'next_role': '',
                'next_step': ''
            }

    with open(path, encoding='utf-8') as f:
        data = json.load(f)

        for feature in data:
            for f, role2code in feature.items():
                for role, codes in role2code.items():
                    state[role] = codes
                    
    return state

# 2️⃣ 에이전트 실행 함수
def run_egov_agent(path='output/java_analysis_results.json') -> Dict[str, Any]:
    state = init_state(path)
    result = egov_crew.kickoff(inputs={"state": state})
    return result

# 3️⃣ CLI 실행 진입점
if __name__ == '__main__':
    result = run_egov_agent()
    print("[✅ 완료] 최종 상태:", result)
    
    with open("./test.json", 'w', encoding='utf-8') as f:
        json.dump(result.tasks_output[-1].pydantic.model_dump(), f, ensure_ascii=False, indent=2)