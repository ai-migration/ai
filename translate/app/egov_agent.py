from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langchain.vectorstores import FAISS
from langchain_core.output_parsers import JsonOutputParser

from translate.app.states import ConversionEgovState
from translate.app.producer import MessageProducer
from translate.app.prompts import controller_template, service_prompt, serviceimpl_prompt, vo_prompt

import json
import os

LLM = 'gpt-4o'
EMBEDDING = 'text-embedding-3-small'
DB_PATH = r'C:\Users\User\Desktop\dev\project\eGovCodeDB_0805'

class ConversionEgovAgent:
    def __init__(self):
        self.llm = ChatOpenAI(model=LLM, temperature=0)
        self.embedding =  OpenAIEmbeddings(model=EMBEDDING)
        vectordb = FAISS.load_local(DB_PATH, embeddings=self.embedding, allow_dangerous_deserialization=True)
        self.retriever = vectordb.as_retriever(search_kwargs={"k": 3})
        self.producer = MessageProducer()

    def init_state(self, user_id, job_id, path='output/java_analysis_results.json'):
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
                    'user_id': user_id,
                    'job_id': job_id,
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

    def is_finished(self, state):
        roles = ['controller', 'service', 'serviceimpl', 'vo']
        for role in roles:
            raw_cnt = len(state.get(role, []) or [])
            conv_cnt = len(state.get(f"{role}_egov", []) or [])
            if raw_cnt > conv_cnt:  # 아직 변환할 대상이 남아있음
                state['next_step'] = 'continue'
                return state
        state['next_step'] = 'completed'

        print('1️⃣ 완성 여부 체크:', state['next_step'])
        return state
    
    def next_processing(self, state):
        roles = ['controller','service','serviceimpl','vo']

        for role in roles:
            if state[role] and len(state[role]) != len(state[f"{role}_egov"]):
                state['next_role'] = role
                state['next_step'] = 'continue'
                return state
            
        state['next_step'] = 'completed'
                
        print(f"2️⃣ 모든 계층 변환 완료")
        return state 

    def search_egov_code(self, state):
        print(f"3️⃣ 유사 코드 검색")
        role = state.get('next_role')
    
        if not role:
            return state

        results = []
        for code in state.get(role, []):
            query = f"[description]\n[role]{role}\n[code]{code}"
            docs = self.retriever.get_relevant_documents(query)
            cands = [d.page_content.split('[code]')[-1] for d in docs if d.metadata.get('type','').lower()==role]
            results.append(cands[0] if cands else "")
        
        state['retrieved'] = results

        return state
    
    def converse_code(self, state):
        '''
        변환 출력 포맷은 prompttemplate 확인
        '''
        parser = JsonOutputParser()

        role = state['next_role']
        print(f"4️⃣ {role} 계층 변환 및 생성:")
        
        if role == 'controller':
            chain = controller_template | self.llm | parser

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
            chain = service_prompt | self.llm | parser

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
            chain = serviceimpl_prompt | self.llm | parser

            for idx, code in enumerate(state[role]):
                res = chain.invoke({'INPUT_SERVICEIMPL_CODE': code,
                                    'EGOV_EXAM_CODE': state['retrieved'][idx]})

                state['serviceimpl_egov'].append(res['ServiceImpl']['code'])
                state['serviceimpl_report']['conversion'] = (res['ServiceImpl']['report'])
        
        if role == 'vo':
            chain = vo_prompt | self.llm | parser

            for idx, code in enumerate(state[role]):
                res = chain.invoke({'INPUT_DTO_CODE': code,
                                    'EGOV_EXAM_CODE': state['retrieved'][idx]})

                state['vo_egov'].append(res['VO']['code'])
                state['vo_report']['conversion'] = res['VO']['report']

        self.producer.send_message(topic='agent-res', 
                                    message={'userId': state['user_id'], 'jobId': state['job_id'], 'status': 'SUCCESS', 'description': f"전자정부 표준 프레임워크의 {role} 계층 코드 변환이 완료되었습니다."},
                                    headers=[('AGENT', 'EGOV')])
        
        return state

    def build_graph(self):
        builder = StateGraph(ConversionEgovState) 

        builder.add_node('complete', self.is_finished)
        builder.add_node('next', self.next_processing)
        builder.add_node('rag', self.search_egov_code)
        builder.add_node('conversion', self.converse_code)

        builder.add_edge(START, 'complete')
        builder.add_conditional_edges('complete', lambda state: state['next_step'], {'completed': END, 'continue': 'next'})
        builder.add_edge('next', 'rag')
        builder.add_edge('rag', 'conversion')
        builder.add_edge('conversion', 'complete')

        graph = builder.compile()
        # print(graph.get_graph().draw_mermaid())
        # graph.get_graph().draw_mermaid_png(output_file_path='egov_agent.png')
        return graph

if __name__ == '__main__':
    # state = CoversionEgovState(input_path={'controller': [r'C:\Users\User\Desktop\dev\project\BoardController.java'],
    #                                        'serviceimpl': [r'C:\Users\User\Desktop\dev\project\BoardService.java'],
    #                                        'vo': [r'C:\Users\User\Desktop\dev\project\BoardUpdateDto.java']},
    #                             controller=[],
    #                             controller_egov=[],
    #                             service=[],
    #                             service_egov=[],
    #                             serviceimpl=[],
    #                             serviceimpl_egov=[],
    #                             vo=[],
    #                             vo_egov=[],
    #                             validate='',
    #                             retrieved=[],
    #                             next_role='',
    #                             next_step='',
    #                             controller_report={},
    #                             service_report={},
    #                             serviceimpl_report={},
    #                             vo_report={})
    agent = ConversionEgovAgent()
    state = agent.init_state(1, 1)
    graph = agent.build_graph()
    result = graph.invoke(state)
    with open('testest.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)