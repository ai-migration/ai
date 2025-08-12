from crewai import Agent, Task, Crew
from pydantic import BaseModel

from egov_tools import preprocessing, check_completed, converse_code, search_egov_code, next_conversion_step, produce_to_kafka
import os

os.environ['OPENAI_API_KEY'] = ''

class OutputFormat(BaseModel):
    input_path: dict
    controller: list
    controller_egov: list
    controller_report: dict
    service: list
    service_egov: list
    service_report: dict
    serviceimpl: list
    serviceimpl_egov: list
    serviceimpl_report: dict
    vo: list
    vo_egov: list
    vo_report: dict
    retrieved: list
    validate: str
    next_role: str
    next_step: str

class InputFormat(BaseModel):
    state: OutputFormat

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
    tools=[preprocessing, check_completed, converse_code, search_egov_code, next_conversion_step, produce_to_kafka],
    memory=False,
    verbose=True
)

init_step_task = Task(
    description=(
        "다음은 입력으로 받은 state이다:\n"
        "{state}\n\n"
        "위 state를 그대로 사용해 check_completed(state=state)를 한 번 호출하여 next_step을 세팅하라.\n"
        "최종 state를 OutputFormat 스키마로 JSON만 출력하라."
    ),
    agent=egov_conv_agent,
    tools=[check_completed],
    # input_variables=["controller", "service", "serviceimpl", "vo"],
    args_schema=InputFormat,
    output_json=OutputFormat, 
    expected_output="초기화된 state"
)

converse_task = Task(
    description=(
        "아래는 이전 단계의 최종 state가 담긴 JSON 문자열(context)이다.\n"
        "{state}\n"
        "항상 가장 최신의 state만 사용해 도구를 호출한다.\n\n"

        
        "다음 규칙을 따라라:\n"
        "1) 위 JSON 문자열에서 최상위의 state 객체를 안전하게 파싱해 변수명 state(dict)로 사용한다.\n"
        "   - 파싱 실패 시, 마지막에 등장하는 JSON 객체를 state로 시도한다.\n"
        "   - state에 controller_egov 등 egov 필드가 없으면 빈 리스트로 기본값을 채운다.\n"
        "2) state.next_step이 'completed'이면 아무 도구도 호출하지 말고 state만 JSON으로 출력하고 종료한다.\n"
        "3) 그렇지 않다면 다음 순서로 각 도구를 정확히 한 번씩 호출한다(인자는 모두 state=state):\n"
        "   - next_conversion_step(state=state)\n"
        "   - search_egov_code(state=state)\n"
        "   - converse_code(state=state)\n"
        "   호출이 끝나면 check_completed(state=state)를 호출해 다음 step을 결정한다.\n"
        # "4) 직전 툴의 반환 state를 그대로 다음 툴에 state=...로 전달하라. 새로운 JSON을 만들지 말라.\n"
        "최종 state를 OutputFormat 스키마로 JSON만 출력하라."
    ),
    agent=egov_conv_agent,
    tools=[next_conversion_step, search_egov_code, converse_code, check_completed],
    context=[init_step_task],
    # args_schema=InputFormat,
    output_json=OutputFormat, 
    expected_output="변환 진행 후 최신 state"
)

response_task = Task(
    description=(
        "이전 단계의 최종 state_json을 Kafka에 발행하라. "
        "produce_to_kafka 도구를 사용한다. "),
    agent=egov_conv_agent,
    tools=[produce_to_kafka],
    context=[converse_task],
    args_schema=InputFormat,
    output_json=OutputFormat, 
    expected_output="Kafka에 발행된 최종 분석 결과"
)

crew = Crew(
    agents=[egov_conv_agent],
    tasks=[init_step_task, converse_task],
    # tasks=[init_step_task, converse_task, response_task],
    verbose=True, memory=True
)

if __name__ == '__main__':
    import tempfile
    import json
    input_zip_path = r'C:\Users\User\Desktop\dev\project\0811test.zip'  

    input = {'controller': [r'C:\Users\User\Desktop\dev\project\BoardController.java'],
            'serviceimpl': [],
            # 'serviceimpl': [r'C:\Users\User\Desktop\dev\project\BoardService.java'],
            'service': [],
            'vo': []}
            # 'vo': [r'C:\Users\User\Desktop\dev\project\BoardUpdateDto.java']}
    
    initial_state = {
        'controller': [],
        'service': [],
        'serviceimpl': [],  
        'vo': [],

        'controller_egov': [],
        'service_egov': [],
        'serviceimpl_egov': [],
        'vo_egov': [],

        'input_path': {},
        'controller_report': {},
        'service_report': {},
        'serviceimpl_report': {},
        'vo_report': {},
        'retrieved': [],
        'validate': '',
        'next_role': '',
        'next_step': ''
    }
    for role, paths in input.items():
        for p in paths:
            with open(p, encoding='utf-8') as f:
                code = f.read()
                initial_state[role].append(code)
    print(f"초기화된 state: {initial_state}")
    result = crew.kickoff(inputs={'state': initial_state})