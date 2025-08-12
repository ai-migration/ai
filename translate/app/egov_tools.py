from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.vectorstores import FAISS
from langchain_core.output_parsers import JsonOutputParser

from crewai import Agent, Task, Crew
from crewai.tools import tool

from prompts import controller_template, service_prompt, serviceimpl_prompt, vo_prompt
from producer import MessageProducer
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

        # builder.add_node('preprocessing', self.preprocessing)
        # builder.add_node('complete', self.is_finished)
        # builder.add_node('next', self.next_processing)
        # builder.add_node('rag', self.search_egov_code)
        # builder.add_node('conversion', self.converse_code)

@tool('preprocessing')
def preprocessing(controller: list = [], service: list = [], serviceimpl: list = [], vo: list = []) -> dict:
    """
    입력된 코드로 state를 초기화합니다.
    """
    state = {
        'controller': controller,
        'service': service,
        'serviceimpl': serviceimpl,  
        'vo': vo,
        'controller_egov': [],
        'service_egov': [],
        'serviceimpl_egov': [],
        'vo_egov': [],
        }
    return {'state': state}

@tool('check_completed')
def check_completed(state: dict) -> dict:
    """
    주어진 상태(state)에서 eGov 변환 대상이 모두 완료되었는지 확인합니다.
    """
    egov_targets = ['controller', 'service', 'serviceimpl', 'vo']
    is_completed = True
    for role in egov_targets:
        # 변환 대상이 있을 때만 egov 리스트가 모두 채워졌는지 확인
        if state[role]:
            if not state[f"{role}_egov"] or len(state[role]) != len(state[f"{role}_egov"]):
                is_completed = False
                break
    
    if is_completed:
        state['next_step'] = 'completed'

        # with open("agent_test5.json", "w", encoding='utf-8') as json_file:
        #     json.dump(state, json_file, ensure_ascii=False, indent=2)
        # producer.send_message('agent-res', message=state)

    else:
        state['next_step'] = 'continue'

    return {'state': state}

@tool('next_conversion_step')
def next_conversion_step(state: dict) -> dict:
    """
    다음 변환 대상 계층을 결정합니다.
    """
    egov_targets = ['controller', 'service', 'serviceimpl', 'vo']
    for role in egov_targets:
        # 변환 대상 코드가 있을 때만 변환 진행
        if state[role]:
            if len(state[role]) != len(state[f"{role}_egov"]):
                state['next_role'] = role
                state['next_step'] = 'conversion'
                return {'state': state}
            
    return {'state': state}

@tool('search_egov_code')
def search_egov_code(state: dict) -> dict:
    """
    주어진 상태(state)에서 유사한 eGov 코드를 검색합니다.
    """
    role = state['next_role']
    results = []
    for code in state[role]:
        query = f"[description]\n[role]{role}\n[code]{code}"

        docs = retriever.get_relevant_documents(query)
        role_exam_codes = []
        for i in docs:
            print('✅ 검색된 문서', i.metadata, role)
            if i.metadata['type'].lower() == role:
                exam_code = i.page_content.split('[code]')[-1]
                role_exam_codes.append(exam_code)

        results.append(role_exam_codes[0])

    state['retrieved'] = results
    print('AAAAAAAAAAAAAAAAAAAAAAAAA:', state.keys())
    return {'state': state}

@tool('conversion')
def converse_code(state: dict) -> dict:
    """
    검색된 eGov 코드를 기반으로 변환 작업을 수행합니다.
    """
    print('BBBBBBBBBBBBBBBBBBBBBBB:', state.keys())
    parser = JsonOutputParser()

    role = state['next_role']
    print(f"4️⃣ {role} 계층 변환 및 생성:")
    
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

    return {'state': state}

@tool('produce_to_kafka')
def produce_to_kafka(state: dict):
    """
    최종 분석 결과를 Kafka로 발행합니다."""
    producer.send_message('agent-res', message=state)
