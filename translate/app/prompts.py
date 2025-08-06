from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser

parser = JsonOutputParser()

controller_template = PromptTemplate(
    template="""
입력 코드는 Controller 계층의 Java 코드입니다.

이 코드를 기반으로, 전자정부표준프레임워크(eGovFrame) 스타일에 맞게 변환하고, 이 Controller에서 유추 가능한 다른 계층(Service, VO)의 코드도 함께 생성합니다.
변환 및 생성 과정 리포트를 작성합니다.

[입력 코드 - Controller]
{INPUT_CONTROLLER_CODE}

[참조 코드 - 관련 Service 인터페이스]
{INPUT_SERVICE_CODE}

[참조 코드 - 전자정부표준프레임워크 예시 코드]
{EGOV_EXAM_CODE}

[역할 설명]
- 웹 요청을 받아 Service 계층의 메서드를 호출하고, 그 결과를 JSP 뷰로 반환합니다.
- 사용되는 DTO는 전자정부표준프레임워크에서 VO(Value Object)로 간주합니다.

[변환 요구사항]
- 반드시 전자정부표준프레임워크 규칙을 반영합니다.
- 클래스명은 `~Controller`, 위치는 `egovframework.[도메인].web`
- Controller 코드에서 호출되는 메서드나 파라미터를 분석해 필요한 Service 인터페이스 또는 VO 클래스가 있다면 생성합니다.
- Controller 계층은 Service 계층과 VO 계층을 호출합니다.
- Service 인터페이스와 VO 클래스는 생성할 때 기본적인 구현을 포함합니다.
- 변환 및 생성 리포트를 계층 별로 작성합니다.

[리포트 내용]
- 변경 사항
- 추가 사항
- 변환 및 생성 요약

[출력 형식]
- 각 계층별 코드는 다음 포맷으로 출력합니다:
```json
{{
  "Controller": {{
    "code": "<전자정부프레임워크 스타일의 Controller 코드>",
    "report": {{"변경 사항": "<변경 사항>",
                "추가 사항": "<추가 사항>",
                "요약": "<변환 및 생성 요약>"
    }}
  }},
  "Service": {{
    "code": "<생성된 Service 인터페이스 코드>",
    "report": {{"변경 사항": "<변경 사항>",
                "추가 사항": "<추가 사항>",
                "요약": "<변환 및 생성 요약>"
    }}
  }},
  "VO": {{
    "code": "<생성된 VO 코드>",
    "report": {{"변경 사항": "<변경 사항>",
                "추가 사항": "<추가 사항>",
                "요약": "<변환 및 생성 요약>"
    }}
  }}
}}
- code와 report 외에는 아무것도 출력하지 않습니다.
""",
    input_variables=['INPUT_CONTROLLER_CODE', 'INPUT_SERVICE_CODE', 'EGOV_EXAM_CODE'],
    partial_variables={"format_instructions": parser.get_format_instructions()}
)

service_prompt = PromptTemplate(
    input_variables=['INPUT_SERVICE_CODE', 'INPUT_CONTROLLER_CODE', 'EGOV_EXAM_CODE'],
    template="""
입력 코드는 Service 인터페이스(Java)의 코드입니다.

이 코드를 기반으로, 전자정부표준프레임워크(eGovFrame) 스타일에 맞게 변환하고, 이 Service에서 유추 가능한 다른 계층(ServiceImpl)의 코드도 함께 생성합니다.
변환 및 생성 과정 리포트를 작성합니다.

[입력 코드 - Service 인터페이스]
{INPUT_SERVICE_CODE}

[참조 코드 - Controller]
{INPUT_CONTROLLER_CODE}

[참조 코드 - 전자정부표준프레임워크 예시 코드]
{EGOV_EXAM_CODE}

[역할 설명]
- Service 인터페이스는 Controller 계층과 ServiceImpl 계층 사이의 비즈니스 로직 인터페이스 역할을 합니다.
- 각 메서드에 대한 구현은 ServiceImpl로, DB 연동 로직은 DAO 계층으로 분리됩니다.

[변환 요구사항]
- 반드시 전자정부표준프레임워크 규칙을 반영합니다.
- 클래스명은 `~Service`, 위치는 `egovframework.[도메인].service`
- Service 인터페이스에서 호출되는 메서드나 파라미터를 분석해 필요한 ServiceImpl 클래스가 있다면 생성합니다.
- ServiceImpl 생성 할 때 Service 인터페이스의 모든 메서드에 대해 기본적인 구현을 생성합니다. 
- 변환 및 생성 리포트를 계층 별로 작성합니다.

[리포트 내용]
- 변경 사항
- 추가 사항
- 변환 및 생성 요약

[출력 형식]
- 각 계층별 코드는 다음 포맷으로 출력합니다:
```json
{{
  "Service": {{
    "code": "<전자정부프레임워크 스타일의 Service 코드>",
    "report": {{"변경 사항": "<변경 사항>",
                "추가 사항": "<추가 사항>",
                "요약": "<변환 및 생성 요약>"
    }}
  }},
  "ServiceImpl": {{
    "code": "<생성된 ServiceImpl 코드>",
    "report": {{"변경 사항": "<변경 사항>",
                "추가 사항": "<추가 사항>",
                "요약": "<변환 및 생성 요약>"
    }}
  }}
}}
- code와 report 외에는 아무것도 출력하지 않습니다.
"""
)

serviceimpl_prompt = PromptTemplate(
    input_variables=['INPUT_SERVICEIMPL_CODE', 'EGOV_EXAM_CODE'],
    template="""
입력 코드는 ServiceImpl 코드입니다.

이 코드를 기반으로, 전자정부표준프레임워크(eGovFrame) 스타일에 맞게 변환합니다.
변환 및 생성 과정 리포트를 작성합니다.

[입력 코드]
{INPUT_SERVICEIMPL_CODE}

[참조 코드 - 전자정부표준프레임워크 예시 코드]
{EGOV_EXAM_CODE}

[역할 설명]
- ServiceImpl은 실제 비즈니스 로직을 처리하며 DAO를 통해 DB 작업을 수행합니다.

[변환 요구사항]
- 반드시 전자정부표준프레임워크 규칙을 반영합니다.
- 클래스명은 `~ServiceImpl`, 위치는 `egovframework.[도메인].service.impl`
- ServiceImpl 생성 할 때 Service 인터페이스의 모든 메서드에 대해 기본적인 구현을 생성합니다. 
- ServiceImpl이 호출하는 DAO가 명시되지 않은 경우, 호출할 DAO 인터페이스를 예상하여 사용합니다.
- 변환 및 생성 리포트를 계층 별로 작성합니다.

[리포트 내용]
- 변경 사항
- 추가 사항
- 변환 요약

[출력 형식]
- 각 계층별 코드는 다음 포맷으로 출력합니다:
```json
{{
  "ServiceImpl": {{
    "code": "<전자정부프레임워크 스타일의 ServiceImpl 코드>",
    "report": {{"변경 사항": "<변경 사항>",
                "추가 사항": "<추가 사항>",
                "요약": "<변환 및 생성 요약>"
    }}
  }}
}}
- code와 report 외에는 아무것도 출력하지 않습니다.
"""
)

vo_prompt = PromptTemplate(
    input_variables=['INPUT_DTO_CODE', 'EGOV_EXAM_CODE'],
    template="""
입력 코드는 DTO 코드입니다.

이 코드를 기반으로, 전자정부표준프레임워크(eGovFrame) 스타일에 맞게 변환합니다.
변환 및 생성 과정 리포트를 작성합니다.

[입력 코드]
{INPUT_DTO_CODE}

[참조 코드 - 전자정부표준프레임워크 예시 코드]
{EGOV_EXAM_CODE}

[변환 요구사항]
- 반드시 전자정부표준프레임워크 규칙을 반영합니다.
- 클래스 이름은 `~VO`, 패키지는 `egovframework.[도메인].service`
- getter/setter 직접 작성
- Serializable 구현
- 변환 및 생성 리포트를 계층 별로 작성합니다.

[리포트 내용]
- 변경 사항
- 추가 사항
- 변환 요약

[출력 형식]
- 각 계층별 코드는 다음 포맷으로 출력합니다:
```json
{{
  "VO": {{
    "code": "<전자정부프레임워크 스타일의 VO 코드>",
    "report": {{"변경 사항": "<변경 사항>",
                "추가 사항": "<추가 사항>",
                "요약": "<변환 및 생성 요약>"
    }}
  }}
}}
- code와 report 외에는 아무것도 출력하지 않습니다.
"""
)

if __name__ == '__main__':
    from langchain_openai import ChatOpenAI
    
    llm = ChatOpenAI(model="gpt-4o-mini", api_key='')
    
    chain = controller_template | llm

    res = chain.invoke({'INPUT_CONTROLLER_CODE': '',
                        'INPUT_SERVICE_CODE': '',
                        'EGOV_EXAM_CODE': ''})