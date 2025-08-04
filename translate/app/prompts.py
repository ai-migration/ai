from langchain.prompts import PromptTemplate

controller_template = PromptTemplate(
    input_variables=['INPUT_CONTROLLER_CODE', 'INPUT_SERVICE_CODE', 'EGOV_EXAM_CODE'],
    template="""
다음은 Spring 기반의 사용자 요청을 처리하는 Controller 코드입니다.  
이 코드를 전자정부표준프레임워크(eGovFrame)를 적용하여 Controller 클래스(Java)를 작성해 주세요.

[입력 코드 - Controller (Spring Boot 기반)]
{INPUT_CONTROLLER_CODE}

[참조 코드 - 관련 Service 인터페이스]
{INPUT_SERVICE_CODE}

[참조 코드 - 전자정부표준프레임워크 예시 코드]
{EGOV_EXAM_CODE}

[역할 설명]
- 웹 요청을 받아 Service 계층의 메서드를 호출하고, 그 결과를 JSP 뷰로 반환합니다.
- 사용되는 DTO는 전자정부표준프레임워크에서 VO(Value Object)로 간주합니다.

[변환 요구사항]
1. 클래스 이름은 `~Controller.java` 형식으로 유지합니다.
2. `@RequestMapping` 기반의 URL 매핑 구조는 원본 그대로 반영합니다.
3. 각 메서드는 `ModelMap` 또는 `ModelAndView`를 사용해 뷰에 데이터를 전달합니다.
4. 반환 타입은 JSP View의 논리 이름(`String`)으로 작성하며, 뷰 경로는 `/view/` 하위로 가정합니다.
5. 사용하는 서비스는 참조한 인터페이스에서 정의된 메서드를 호출하고, DI는 `@Resource(name="...")` 방식으로 처리합니다.
6. 클래스 및 메서드에 한글 주석을 추가해 주세요.
7. 로깅은 `LoggerFactory` 대신 `Logger` 또는 `EgovLogger` 인터페이스 사용.
8. 결과는 순수 Java 코드로 출력해 주세요. (불필요한 설명 제외)
"""
)

service_prompt = PromptTemplate(
    input_variables=['INPUT_SERVICE_CODE', 'INPUT_CONTROLLER_CODE', 'EGOV_EXAM_CODE'],
    template="""
다음은 Controller에서 호출할 Service 계층의 로직입니다.  
이 코드를 전자정부표준프레임워크(eGovFrame)를 적용하여 Service interface 클래스(Java)를 작성해 주세요.

[입력 코드 - Service 인터페이스]
{INPUT_SERVICE_CODE}

[참조 코드 - Controller]
{INPUT_CONTROLLER_CODE}

[참조 코드 - 전자정부표준프레임워크 예시 코드]
{EGOV_EXAM_CODE}

[역할 설명]
- Service는 비즈니스 로직의 명세를 정의하며, Controller와 ServiceImpl 간의 규칙입니다.

[요구사항]
1. 인터페이스 이름은 `~Service` 형식, 위치는 `egovframework.[도메인].service`로 가정합니다.
2. Controller에서 호출한 메서드를 기준으로 시그니처 구성
3. 파라미터와 반환 타입은 Controller에서 호출하는 로직을 기반으로 구성하세요.
4. VO 또는 기본 타입을 활용해 주세요. (DTO → VO 전환 가정)
5. 클래스 및 메서드에 한글 주석을 추가해 주세요.
6. 결과는 순수 Java 인터페이스 코드로 출력해 주세요.
"""
)

serviceimpl_prompt = PromptTemplate(
    input_variables=['INPUT_SERVICEIMPL_CODE', 'INPUT_DTO_CLASS', 'EGOV_EXAM_CODE'],
    template="""
다음은 Service 인터페이스입니다.
이 코드를 전자정부표준프레임워크(eGovFrame)를 적용하여 ServiceImpl 클래스(Java)를 작성해주세요.
  
[입력 코드]
{INPUT_SERVICEIMPL_CODE}
 
[참조 코드 - Service 인터페이스]
{INPUT_SERVICE_CODE}

[참조 코드 - 관련 DTO 클래스]
{INPUT_DTO_CLASS}

[참조 코드 - 전자정부표준프레임워크 예시 코드]
{EGOV_EXAM_CODE}

[역할 설명]
- ServiceImpl은 실제 비즈니스 로직을 처리하며 DAO를 통해 DB 작업을 수행합니다.

[요구사항]
1. 클래스명은 `~ServiceImpl`, 위치는 `egovframework.[도메인].service.impl`
2. 인터페이스를 `@Service("...")` 이름으로 구현하며, DAO는 `@Resource(name="...")`로 주입합니다.
3. 메서드 로직은 DAO를 활용해 작성하며, 파라미터와 반환값은 인터페이스 기준을 따릅니다.
4. 클래스 및 메서드에 한글 주석을 추가해 주세요.
5. 로깅은 `Logger` 또는 `EgovLogger` 사용
6. 결과는 순수 Java 코드로 출력해 주세요.
"""
)

serviceimpl_prompt = PromptTemplate(
    input_variables=['INPUT_DTO_CODE', 'EGOV_EXAM_CODE'],
    template="""
다음은 사용자 정보를 담고 있는 DTO 코드입니다. 
이 코드를 전자정부표준프레임워크(eGovFrame)를 적용하여 VO 클래스(Java)를 작성해주세요.

[입력 코드]
{INPUT_DTO_CODE}

[참조 코드 - 전자정부표준프레임워크 예시 코드]
{EGOV_EXAM_CODE}

[요구사항]
1. 클래스 이름은 `~VO`, 패키지는 `egovframework.[도메인].service`
2. VO 클래스의 필드는 DTO 코드에서 유추하여 작성해 주세요. (예: 사용자 ID, 이름 등)
3. 필드는 모두 `private`, getter/setter 포함
4. Lombok을 사용하지 말고, 명시적으로 getter/setter 메서드를 작성해 주세요.
5. 클래스 및 메서드에 한글 주석을 추가해 주세요.
6. 결과는 순수 Java 코드로 출력해 주세요.
"""
)

if __name__ == '__main__':
    from langchain_openai import ChatOpenAI
    
    llm = ChatOpenAI(model="gpt-4o-mini", api_key='')
    
    chain = controller_template | llm

    res = chain.invoke({'INPUT_CONTROLLER_CODE': '',
                        'INPUT_SERVICE_CODE': '',
                        'EGOV_EXAM_CODE': ''})