import os
import re
import json
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from openai import OpenAI
from langchain_openai import ChatOpenAI
from langchain.tools import StructuredTool
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
assert OPENAI_API_KEY, "Missing OPENAI_API_KEY (set in your env)"
llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=OPENAI_API_KEY)


# agent_toolchain.py
# LangGraph/LC agent with StructuredTool I/O, safe env handling, and stable code-block extraction



oai_client = OpenAI(api_key=OPENAI_API_KEY)
llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=OPENAI_API_KEY)

def build_prompt_with_usage(input_data: dict, target_code: str = None,
                            used: bool = False, used_index: int = None) -> str:
    role = input_data.get("role", {}).get("type", "unknown").lower()
    class_name = input_data.get("name", "UnknownClass")
    python_body = input_data.get("body", "")
    path = input_data.get("source_info", {}).get("rel_path", "unknown")

    prompt = f"""
다음은 Python으로 작성된 {role.upper()} 역할의 클래스입니다:
(소스 경로: {path})

```python
{python_body}
```

이 Python 코드를 전자정부프레임워크 기반 Java {role.upper()} 역할 클래스로 변환하세요.
- 클래스명은 `{class_name}{role.capitalize()}` 또는 역할에 맞는 이름으로 설정하세요.
- 역할은 `{role.upper()}`로 고정되어 있습니다.
""".strip()

    if used and target_code:
        prompt += f"""

아래는 이 역할({role.upper()})의 기존 Java 클래스입니다.
(index: {used_index})

```java
{target_code}
```

[판단 기준]
- 위 클래스를 **수정하거나 확장하는 방식**으로 통합하세요.
- 중복 정의 없이 구조를 정리하고, 누락 없이 재생성해도 됩니다.
""".rstrip()
    else:
        prompt += """

[판단 기준]
- 기존 Java 클래스가 없으므로 **새 클래스를 생성**하세요.
""".rstrip()

    prompt += """

[출력 지침]
- **오직 하나의 완성된 Java 코드**만 출력하세요. (주석/설명 금지)
- 코드블록 표기는 허용하나, 내부는 완전한 Java 소스여야 합니다.
""".rstrip()
    return prompt



class PromptBuilderInput(BaseModel):
    state: Dict[str, Any]

def prompt_builder_tool_func(state: Dict[str, Any]) -> str:
    input_data = state["input"]
    target_code_list: List[str] = state.get("role_code", [])
    used = bool(state.get("used", False))
    used_index_raw = state.get("used_index", None)
    used_index = (
        int(used_index_raw)
        if isinstance(used_index_raw, (int, float)) or (isinstance(used_index_raw, str) and used_index_raw.isdigit())
        else None
    )

    target_code = None
    if used and used_index is not None and 0 <= used_index < len(target_code_list):
        target_code = target_code_list[used_index]

    return build_prompt_with_usage(
        input_data=input_data,
        target_code=target_code,
        used=used,
        used_index=used_index,
    )

prompt_builder_tool = StructuredTool.from_function(
    name="prompt_builder_tool",
    description="역할 기반 Java 생성 프롬프트 구성",
    func=lambda state: prompt_builder_tool_func(state),
)

# class CodeGenArgs(BaseModel):
#     prompt: str
def extract_code_block(text: str, language: str = "java") -> str:
    m = re.search(fr"```{language}\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()

def gpt_code_generator_tool_func(prompt: str) -> str:
    resp = oai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "전자정부프레임워크 Java 개발 전문가입니다."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    raw = resp.choices[0].message.content or ""
    return extract_code_block(raw, "java")

gpt_code_generator_tool = StructuredTool.from_function(
    name="gpt_code_generator_tool",
    description="프롬프트를 기반으로 Java 코드를 생성",
    func=lambda prompt: gpt_code_generator_tool_func(prompt),
)


# class RoleUsageArgs(BaseModel):
#     state: Dict[str, Any]

class RoleUsageResult(BaseModel):
    used: bool
    used_index: Optional[int] = Field(default=None)

def _extract_class_name(java_code: str) -> str:
    m = re.search(r"\bclass\s+([A-Za-z_]\w*)", java_code)
    return m.group(1) if m else "UnknownClass"

def role_usage_selector_func(state: Dict[str, Any]) -> RoleUsageResult:
    input_data = state["input"]
    code_list: List[str] = state.get("role_code", [])
    py_body = input_data.get("body", "")

    prompt_parts = [
        "다음은 Python 코드입니다:\n",
        "```python", py_body, "```",
        "\n아래는 현재까지 존재하는 Java 클래스 후보 목록입니다:\n",
    ]
    for i, code in enumerate(code_list):
        prompt_parts += [
            f"\nindex : [{i}] 클래스명: {_extract_class_name(code)}\n```java\n",
            code,
            "\n```",
        ]
    prompt_parts += [
        (
            """
당신의 역할:
- 위 Python 코드가 위 Java 코드 중 어떤 클래스와 가장 연관이 깊은지 판단하세요.
- 또한 역할을 고려하며 자바 프레임워크에서 클래스를 어떻게 관리하는게 좋을지 고려하세요.
- 만약 연관된 클래스가 있다면 해당 인덱스 번호(index)를 반환하고, used=True로 표시하세요.
- 어떤 클래스와도 관련이 없으면 used=False로 표시하고 index는 null로 설정하세요.

[출력 형식: JSON만]
{"used": True/False, "used_index": 인덱스 또는 null}
            """.strip()
        )
    ]

    resp = oai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "역할 기반 코드 유사성 판단 전문가입니다."},
            {"role": "user", "content": "\n".join(prompt_parts)},
        ],
        temperature=0,
    )
    raw = (resp.choices[0].message.content or "").strip()
    raw = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()
    print(raw)
    try:
        data = json.loads(raw)
        used = bool(data.get("used", False))
        used_index = data.get("used_index", None)
        if used and (used_index is None or not isinstance(used_index, int)):
            used, used_index = False, None
    except Exception:
        used, used_index = False, None
    return RoleUsageResult(used=used, used_index=used_index)

role_usage_selector = StructuredTool.from_function(
    name="role_usage_selector",
    description="기존 Java 후보와의 연관성 판단",
    func=lambda state: role_usage_selector_func(state),  # 그냥 dict 받도록
)



TOOLS = [role_usage_selector, prompt_builder_tool, gpt_code_generator_tool]

agent_prompt = ChatPromptTemplate.from_messages([
    ("system", "너는 Python 코드를 전자정부프레임워크 Java로 변환하는 전문가다."),
    (
        "human",
        "다음 state를 사용해서 순서대로:\n"
        "1) role_usage_selector로 used/used_index 결정\n"
        "2) prompt_builder_tool로 프롬프트 생성\n"
        "3) gpt_code_generator_tool로 Java 코드 생성\n\n"
        "반드시 마지막에 아래 JSON만 출력:\n"
        "{{ 'java': <생성코드 그대로>, 'used_index': <숫자 또는 null(무조건 null!!! None같은 다른 표현 절대 안됨)> }}\n"
        "state:\n{state}",
    ),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm=llm, tools=TOOLS, prompt=agent_prompt)
agent_executor = AgentExecutor(agent=agent, tools=TOOLS, verbose=True, handle_parsing_errors=True)



from langgraph.graph import StateGraph
from langgraph.graph import END
from typing import TypedDict, Optional
from typing import TypedDict, List, Set
# 상태 정의
class JavaGenState(TypedDict):
    input: dict  # 현재 처리 중인 Python 클래스 or 함수 정보

    # 생성된 코드 저장 필드 (역할별, 모두 리스트 형태)
    controller_code: List[str]
    service_code: List[str]
    dto_code: List[str]
    configuration_code: List[str]
    util_code: List[str]
    entity_code: List[str]

    end: bool  # LangGraph 종료 조건

CLASSES: list[dict] = []

def load_classes(jsonl_path: str):
    global CLASSES
    with open(jsonl_path, "r", encoding="utf-8") as f:
        CLASSES = [json.loads(line) for line in f]

def pop_next_class_node(state: dict) -> dict:
    if not CLASSES:
        state["end"] = True
        return state

    state["input"] = CLASSES.pop(0)
    state["end"] = False
    return state

import json

def generate_java_code_node(state: dict) -> dict:
    input_data = state["input"]
    role_type = input_data.get("role", {}).get("type", "").upper()

    # 역할별 저장 위치
    role_map = {
        "CONTROLLER": "controller_code",
        "SERVICE": "service_code",
        "DTO": "dto_code",
        "CONFIGURATION": "configuration_code",
        "UTIL": "util_code",
        "ENTITY": "entity_code",
    }

    # key 미리 세팅 (없으면 util_code로)
    key = role_map.get(role_type, "util_code")

    # agent 입력 준비
    role_key = input_data.get("role", {}).get("type", "").lower()
    agent_input = {
        "input": input_data,
        "role_code": state.get(f"{role_key}_code", []),
        "used": False,
        "used_index": None
    }

    # agent 실행
    try:
        raw_result = agent_executor.invoke({"state": json.dumps(agent_input, ensure_ascii=False)})
    except Exception as e:
        print(f"⚠️ 에이전트 실행 오류: {e}")
        raw_result = None

    raw_result=str(raw_result['output'])
    fruits = re.search(r"['\"]java['\"]\s*:\s*((?:.|\n)*)", raw_result.strip())
    aa=re.search(r"['\"]used_index['\"]\s*:\s*((?:.|\n)*)", fruits[1])
    bb=aa[1].split("}")
    java_code, used_index = fruits[1].strip(), bb[0].strip()

    # 코드 저장
    bucket = state.setdefault(key, [])
    # used_index가 "null"이 아닌 경우 (즉, 유효한 정수일 때)
    if used_index != "null":
        # 기존 항목을 업데이트합니다.
        bucket[int(used_index)] = java_code
    else:
        # used_index가 "null"인 경우, 새로운 항목을 추가합니다.
        bucket.append(java_code)

    return state

def check_class_remaining_node(state: dict) -> dict:
    state["end"] = not bool(CLASSES)  # 비어있으면 True, 남아있으면 False
    return state

# --- 저장 노드 교정안 ---

def _extract_java_class_name(code: str) -> str:
    m = re.search(r"\bclass\s+([A-Za-z_]\w*)", code)
    return m.group(1) if m else "Generated"

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def save_to_egov_tree_node(state: dict) -> dict:
    """
    LangGraph 노드: state에 쌓인 역할별 Java 코드들을
    eGov 디렉터리 트리에 일괄 저장한다. (state -> state)
    """
    # 1) 출력 루트 결정
    outdir = state.get("outdir", "egov_generated_project")

    # 2) 역할별 디렉터리 매핑 (필요시 SERVICEIMPL 추가)
    mapping = {
        "CONTROLLER":   "egovframework/com/cop/bbs/controller",
        "SERVICE":      "egovframework/com/cop/bbs/service",
        "SERVICEIMPL":  "egovframework/com/cop/bbs/service/impl",
        "DTO":          "egovframework/com/cop/bbs/vo",
        "ENTITY":       "egovframework/com/cop/bbs/vo",
        "CONFIGURATION":"egovframework/com/config",
        "UTIL":         "egovframework/com/common/util",
    }

    # 3) state 버킷 → role 매핑
    buckets = {
        "CONTROLLER":  state.get("controller_code", []),
        "SERVICE":     state.get("service_code", []),
        "DTO":         state.get("dto_code", []),
        "CONFIGURATION": state.get("configuration_code", []),
        "UTIL":        state.get("util_code", []),
        "ENTITY":      state.get("entity_code", []),
        # 필요시 SERVICEIMPL 버킷도 추가:
        "SERVICEIMPL": state.get("serviceimpl_code", []),
    }

    # 4) 일괄 저장
    for role, code_list in buckets.items():
        if not code_list:
            continue

        subdir = mapping.get(role, "egovframework/com/common/util")
        target_dir = os.path.join(outdir, subdir)
        _ensure_dir(target_dir)

        for idx, code in enumerate(code_list):
            if not isinstance(code, str) or not code.strip():
                continue

            class_name = _extract_java_class_name(code)
            # 파일명: 클래스명 우선, 없으면 role+index
            filename = f"{class_name}.java" if class_name else f"{role.title()}{idx+1}.java"
            path = os.path.join(target_dir, filename)

            with open(path, "w", encoding="utf-8") as f:
                f.write(code)

    # 저장 후 state 그대로 반환 (필요시 저장 경로 목록도 추가 가능)
    return state



from langgraph.graph import StateGraph, END

builder = StateGraph(JavaGenState)

# 노드 등록
builder.add_node("PopClass", pop_next_class_node)
builder.add_node("GenerateJava", generate_java_code_node)
builder.add_node("CheckRemaining", check_class_remaining_node)
builder.add_node("SaveAll", save_to_egov_tree_node)

# 시작점
builder.set_entry_point("PopClass")

# 순차적 연결
builder.add_edge("PopClass", "GenerateJava")
builder.add_edge("GenerateJava", "CheckRemaining")

# 조건 분기
builder.add_conditional_edges(
    "CheckRemaining",
    # 분기 기준
    lambda state: "end" if state.get("end") else "PopClass",
    # 분기 결과
    {
        "PopClass": "PopClass",  # 반복
        "end": "SaveAll",              
    }
)
graph_executor = None

def build_executor():
    global graph_executor
    if graph_executor is None:
        print("[🔧] LangGraph 컴파일 시작")
        graph_executor = builder.compile()
        print("[✅] LangGraph 컴파일 완료")

# ✅ 2. 실행 함수
def run_python_agent(jsonl_path="output/classes.jsonl", limit=None):
    # 클래스 로드
    load_classes(jsonl_path)
    print(f"[INFO] 전체 클래스 수: {len(CLASSES)}")

    # 제한 설정
    if limit:
        limited = CLASSES[:limit]
    else:
        limited = CLASSES

    print(f"[INFO] 실행할 클래스 수: {len(limited)}")

    # LangGraph 실행기 준비
    build_executor()

    # 초기 상태 정의
    state = {
        "input": {},  # 여기에 한 개씩 넣어야 함
        "controller_code": [],
        "service_code": [],
        "dto_code": [],
        "configuration_code": [],
        "util_code": [],
        "entity_code": [],
        "used": False,
        "used_index": None,
        "end": False,
    }

    # 첫 클래스만 우선 실행 (개별적으로 처리 가능)
    if limited:
        state["input"] = limited[0]  # 여기부터 순차 반복 가능
        return graph_executor.invoke(state)
    else:
        print("[⚠️] 실행할 클래스가 없습니다.")
        return state

# ✅ 3. CLI 실행 진입점
if __name__ == "__main__":
    result = run_python_agent(limit=2)
    print("[✅ 완료] 최종 상태:", result)