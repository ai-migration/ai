from crewai import Agent, Task, Crew
from pydantic import BaseModel

from egov_tools import CheckCompletedTool, ConversionTool, ProduceTool
import os

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
    verbose=True
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
    expected_output="최종 state(dict)"
)

response_task = Task(
    description=(
        "이전 단계의 최종 state를 Kafka에 발행하라. "
        "produce_to_kafka 도구를 사용한다. "),
    agent=egov_conv_agent,
    tools=[produce],
    context=[conversion_task],
    expected_output="최종 분석 결과를 kafka로 메세지 발행"
)

crew = Crew(
    agents=[egov_conv_agent],
    tasks=[conversion_task, response_task],
    verbose=True, memory=False
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

    result = crew.kickoff(inputs={"state": initial_state})