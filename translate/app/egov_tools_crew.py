from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.vectorstores import FAISS
from langchain_core.output_parsers import JsonOutputParser

from crewai import Agent, Task, Crew
from crewai.tools import tool, BaseTool

from typing import Dict, Any, List, Type, Tuple
from pydantic import BaseModel
import json
from translate.app.prompts import controller_template, service_prompt, serviceimpl_prompt, vo_prompt
from translate.app.producer import MessageProducer
import os

os.environ['OPENAI_API_KEY'] = ''

LLM = 'gpt-4o-mini'
EMBEDDING = 'text-embedding-3-small'
VECTORDB_PATH = r'C:\Users\User\Desktop\dev\project\eGovCodeDB_0805'

producer = MessageProducer()

embedding =  OpenAIEmbeddings(model=EMBEDDING)
vectordb = FAISS.load_local(VECTORDB_PATH, embeddings=embedding, allow_dangerous_deserialization=True)
retriever = vectordb.as_retriever(search_kwargs={"k": 3})
llm = ChatOpenAI(model=LLM)

class State(BaseModel):
    state: dict 

def next_processing_core(state: Dict[str, Any]) -> Dict[str, Any]:
    roles = ['controller','service','serviceimpl','vo']

    for role in roles:
        if state[role] and len(state[role]) != len(state[f"{role}_egov"]):
            state['next_role'] = role
            state['next_step'] = 'continue'
            return state
        
    state['next_step'] = 'completed'

    return state

def search_egov_code_core(state: Dict[str, Any]) -> Dict[str, Any]:
    role = state.get('next_role')
    
    if not role:
        return state

    results: List[str] = []
    for code in state.get(role, []):
        query = f"[description]\n[role]{role}\n[code]{code}"
        docs = retriever.get_relevant_documents(query)
        cands = [d.page_content.split('[code]')[-1] for d in docs if d.metadata.get('type','').lower()==role]
        results.append(cands[0] if cands else "")
    
    state['retrieved'] = results
    
    return state

def produce_core(state: Dict[str, Any]) -> Dict[str, Any]:
    producer.send_message('agent-res', message={'user_id': state['user_id'],
                                                'job_id': state['job_id'],
                                                'status': 'SUCCESS'}, headers=[('agent', 'egov')])

def converse_code_core(state: Dict[str, Any]) -> Dict[str, Any]:
    parser = JsonOutputParser()

    role = state['next_role']
    
    if role == 'controller':
        chain = controller_template | llm | parser

        for idx, code in enumerate(state[role]):
            res = chain.invoke({'INPUT_CONTROLLER_CODE': code,
                                'INPUT_SERVICE_CODE': '\n'.join(f'=== Service class {i+1} ===\n{code}' for i, code in enumerate(state['service'])) if state['service'] else '',
                                'EGOV_EXAM_CODE': state['retrieved'][idx]})
            
            state['controller_egov'].append(res['Controller']['code'])
            state['controller_report']['conversion'] = res['Controller']['report']

            if not state['service']:
                state['service'].append(res['Service']['code'])
                state['service_report']['generate'] = res['Service']['report']

            if not state['vo']:
                state['vo'].append(res['VO']['code'])
                state['vo_report']['generate'] = res['VO']['report']
    
    if role == 'service':
        chain = service_prompt | llm | parser

        for idx, code in enumerate(state[role]):
            res = chain.invoke({'INPUT_SERVICE_CODE': code,
                                'INPUT_CONTROLLER_CODE': '\n'.join(f'=== Controller class {i+1} ===\n{code}' for i, code in enumerate(state['controller'])) if state['controller'] else '',
                                'EGOV_EXAM_CODE': state['retrieved'][idx]})
            
            state['service_egov'].append(res['Service']['code'])
            state['service_report']['conversion'] = res['Service']['report']
            
            if not state['serviceimpl']:
                state['serviceimpl'].append(res['ServiceImpl']['code'])
                state['serviceimpl_report']['generate'] = res['ServiceImpl']['report']
    
    if role == 'serviceimpl':
        chain = serviceimpl_prompt | llm | parser

        for idx, code in enumerate(state[role]):
            res = chain.invoke({'INPUT_SERVICEIMPL_CODE': code,
                                'EGOV_EXAM_CODE': state['retrieved'][idx]})

            state['serviceimpl_egov'].append(res['ServiceImpl']['code'])
            state['serviceimpl_report']['conversion'] = (res['ServiceImpl']['report'])
    
    if role == 'vo':
        chain = vo_prompt | llm | parser

        for idx, code in enumerate(state[role]):
            res = chain.invoke({'INPUT_DTO_CODE': code,
                                'EGOV_EXAM_CODE': state['retrieved'][idx]})

            state['vo_egov'].append(res['VO']['code'])
            state['vo_report']['conversion'] = res['VO']['report']

    return state

def _align_retrieved(state: Dict[str, Any]) -> None:
    """retrieved 길이가 role 코드 개수보다 짧으면 빈 문자열로 패딩."""
    role = state.get('next_role')

    if not role:
        return state
    
    src = len(state.get(role, []))
    retrived_docs = len(state.get('retrieved') or [])
    print(f"Aligning retrieved: want={src}, got={retrived_docs}")
    
    if retrived_docs < src:
        state['retrieved'] = (state.get('retrieved') or []) + [""] * (src - retrived_docs)

    return state

def _progress_conv(state: Dict[str, Any]) -> Tuple[int, int, int, int]:
    """변환 상태 확인"""
    return (
        len(state.get('controller', [])),
        len(state.get('service', [])),
        len(state.get('serviceimpl', [])),
        len(state.get('vo', []))
    ), (
        len(state.get('controller_egov', [])),
        len(state.get('service_egov', [])),
        len(state.get('serviceimpl_egov', [])),
        len(state.get('vo_egov', []))
    )

class CheckCompletedTool(BaseTool):
    name: str = "check_completed"
    description: str = "state를 분석하여 변환을 계속할지(continue) 종료할지(completed) 판정"
    args_schema: Type[BaseModel] = State

    def _run(self, state: dict) -> dict:
        roles = ['controller', 'service', 'serviceimpl', 'vo']
        for role in roles:
            raw_cnt = len(state.get(role, []) or [])
            conv_cnt = len(state.get(f"{role}_egov", []) or [])
            if raw_cnt > conv_cnt:  # 아직 변환할 대상이 남아있음
                state['next_step'] = 'continue'
                return state
        state['next_step'] = 'completed'
        return state

class ConversionTool(BaseTool):
    name: str = "conversion_loop"
    description: str = "입력 dict의 next_step 키 값에 따라 진행/종료 확인 후 진행이면 '다음 변환 계층 설정 -> 유사 코드 검색 -> 변환' 반복 실행"
    args_schema: Type[BaseModel] = State

    def __init__(self, evaluator: CheckCompletedTool, **kwargs):
        super().__init__(**kwargs)
        self._eval = evaluator

    def _run(self, state: dict) -> dict:
        max_iters = 50
        prev_progress: Tuple[int, int, int, int] | None = None # controller, service, serviceimpl, vo

        for i in range(max_iters):
            print(f"✅  Iteration {i+1}")
            # 1) 진행/종료 판단
            state = self._eval._run(state)
            if state.get('next_step') == 'completed':
                print(f"✅  변환 완료: {state['next_step']}")
                return state

            # 2) 다음 계층 선택
            state = next_processing_core(state)  # next_role, next_step=continue
            print(f"1️⃣  완료 상태: {state['next_step']} 계층 {state['next_role']}")
            if state.get('next_step') == 'completed':
                return state

            # 3) RAG
            state = search_egov_code_core(state)
            state = _align_retrieved(state)  # 길이 보정 (index error 방지)

            # 4) 변환
            before_src, before_egov = _progress_conv(state)
            print(f"2️⃣  변환 전 상태: 원본 -> {before_src} egov -> {before_egov}")
            state = converse_code_core(state)
            after_src, after_egov = _progress_conv(state)
            print(f"3️⃣  변환 전 상태: 원본 -> {after_src} egov -> {after_egov}")

            # 5) 무한 루프 방지 용 진행 상태 확인 후 종료 여부 판단 
            if after_egov == prev_progress or after_egov == before_egov:
                state = self._eval._run(state)
                if state.get('next_step') != 'continue':
                    state['next_step'] = 'completed'
                return state

            prev_progress = after_egov

        state['next_step'] = 'completed'
        return state
    
class ProduceTool(BaseTool):
    name: str = "produce_message"
    description: str = "최종 state를 메세지로 발행"
    args_schema: Type[BaseModel] = State
    def _run(self, state: dict) -> dict:
        return produce_core(state)

