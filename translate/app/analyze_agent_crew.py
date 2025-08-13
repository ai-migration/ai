from crewai import Agent, Task, Crew
from pydantic import BaseModel

from ai.translate.app.analyze_tools_crew import State, PreprocessingTool, DetectLanguageTool, AnalyzePythonTool, AnalyzeJavaTool, ProduceToKafkaTool
import os
os.environ['OPENAI_API_KEY'] = ''

preprocessing_tool = PreprocessingTool()
detect_language_tool = DetectLanguageTool()
analyze_python_tool = AnalyzePythonTool()
analyze_java_tool = AnalyzeJavaTool()
produce_to_kafka_tool = ProduceToKafkaTool()

analysis_agent = Agent(
    role="Code Analyzer", 
    goal="주어진 프로젝트 ZIP 파일을 전처리하고, 언어와 프레임워크를 탐지한 뒤, Python 또는 Java 코드 구조를 분석하여 다음 변환 단계에 필요한 보고서를 생성한다.",
    backstory=("나는 다양한 언어와 프레임워크의 내부 구조를 꿰뚫고 있는 숙련된 코드 분석가다. "
                "새로운 프로젝트를 받으면 가장 먼저 압축을 풀고, 파일들을 체계적으로 분류하며, "
                "프로젝트의 주요 언어와 사용된 프레임워크를 정확하게 파악한다. "
                "그 후 세부적인 클래스와 함수 구조, 역할, 관계를 분석하여 "
                "변환팀이 효율적으로 작업할 수 있도록 명확한 보고서를 제공하는 것이 나의 사명이다."),
    tools=[preprocessing_tool, detect_language_tool, analyze_python_tool, analyze_java_tool, produce_to_kafka_tool],
    memory=False, 
    verbose=True
)

detect_task = Task(
    description=(
        "다음 입력으로 전처리를 수행하라.\n"
        "{state}\n\n"
        "반드시 preprocessing 도구를 위 인자로 호출하고 상태를 만든다.\n"
        "detect_language 도구로 언어/프레임워크를 탐지하고 state에 추가한다.\n"
        "최종 state를 JSON으로만 출력하라."
    ),
    agent=analysis_agent,
    tools=[preprocessing_tool, detect_language_tool],
    input_variables=["state"],
    expected_output="언어와 프레임워크가 탐지된 state",
    output_pydantic=State
)

analyze_task = Task(
    description=(
        "이전 단계의 최종 state가 context로 주어진다.\n"
        "context는 JSON이다. 이를 파싱해 변수명 dict타입으로 사용하라.\n"
        "   - 'language' == 'python'  → analyze_python(state=state) 만 호출\n"
        "   - 'language' == 'java'    → analyze_java(state=state) 만 호출\n"
        "   - 그 외/unknown                  → 어떤 분석도 하지 말고 state를 그대로 반환\n"
        "최종 state를 JSON으로만 출력하라."
    ),
    agent=analysis_agent,
    tools=[analyze_java_tool, analyze_python_tool],  # 👈 둘 다 주고, 어떤 걸 쓸지 '설명'으로 결정
    context=[detect_task],            # 👈 분기 근거가 되는 입력을 연결
    expected_output="분석이 반영된 최종 state",
    output_pydantic=State
)

response_task = Task(
    description=(
        "이전 단계의 최종 state_json을 Kafka에 발행하라. "
        "produce_to_kafka 도구를 사용한다. "),
    agent=analysis_agent,
    tools=[produce_to_kafka_tool],
    context=[analyze_task],
    expected_output="Kafka에 발행된 최종 분석 결과",
    output_pydantic=State
)

analyze_crew = Crew(
    agents=[analysis_agent],
    tasks=[detect_task, analyze_task, response_task],
    verbose=True, memory=True
)

if __name__ == '__main__':
    import tempfile
    import json
    input_zip_path = r'C:\Users\User\Desktop\dev\project\0811test.zip'  

    with tempfile.TemporaryDirectory() as temp_dir_path:
        initial_state = {"user_id": 1, "job_id": 100,  "input_path": input_zip_path, "extract_dir": temp_dir_path}

        result = analyze_crew.kickoff(inputs={"state": initial_state})
        print(result)