from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langchain.vectorstores import FAISS
from langchain_core.output_parsers import JsonOutputParser
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

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
        self.tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-reranker-large")
        self.reranker = AutoModelForSequenceClassification.from_pretrained("BAAI/bge-reranker-large")
        self.reranker.eval()
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
                        if role == 'dto': role = 'vo'
                        state[role] = codes
                        
        return state

    def is_finished(self, state):
        state['retrieved'] = []

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
        print(f"2️⃣ 다음 변환할 계층 확인")

        roles = ['controller','service','serviceimpl','vo']

        for role in roles:
            if state[role] and len(state[role]) != len(state[f"{role}_egov"]):
                state['next_role'] = role
                state['next_step'] = 'continue'
                return state
            
        state['next_step'] = 'completed'
                
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
            cands = [d.page_content for d in docs if d.metadata.get('type','').lower()==role]

            results.append(cands if cands else [])
        
        state['retrieved'] = results

        return state
    
    def rerank_rag(self, state):
        print(f"4️⃣ 검색 결과 rerank")
        role = state.get('next_role')

        results = []
        for i, code in enumerate(state.get(role, [])):
            query = f"[description]\n[role]{role}\n[code]{code}"
            cands = state['retrieved'][i]

            pairs = [(query, cand) for cand in cands]
            
            with torch.no_grad():
                inputs = self.tokenizer(pairs, padding=True, truncation=True, return_tensors="pt")
                scores = self.reranker(**inputs).logits.squeeze(-1)
                ranked = sorted(zip(cands, scores), key=lambda x: x[1], reverse=True)
                top = ranked[0][0] if ranked else ""
                results.append(top)

        state['retrieved'] = results

        return state   

    def converse_controller(self, state):
        parser = JsonOutputParser()

        role = state['next_role']
        print(f"4️⃣ {role} 계층 변환 및 생성:")

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
        
        self.producer.send_message(topic='agent-res', 
                                    message={'userId': state['user_id'], 'jobId': state['job_id'], 'status': 'SUCCESS', 'description': f"전자정부 표준 프레임워크의 {role} 계층 코드 변환이 완료되었습니다."},
                                    headers=[('AGENT', 'EGOV')])
        
        return state
    
    def converse_service(self, state):
        parser = JsonOutputParser()

        role = state['next_role']
        print(f"4️⃣ {role} 계층 변환 및 생성:")

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

        self.producer.send_message(topic='agent-res', 
                                    message={'userId': state['user_id'], 'jobId': state['job_id'], 'status': 'SUCCESS', 'description': f"전자정부 표준 프레임워크의 {role} 계층 코드 변환이 완료되었습니다."},
                                    headers=[('AGENT', 'EGOV')])
        
        return state
    
    def converse_serviceimpl(self, state):
        parser = JsonOutputParser()

        role = state['next_role']
        print(f"4️⃣ {role} 계층 변환 및 생성:")

        chain = serviceimpl_prompt | self.llm | parser

        for idx, code in enumerate(state[role]):
            res = chain.invoke({'INPUT_SERVICEIMPL_CODE': code,
                                'EGOV_EXAM_CODE': state['retrieved'][idx]})

            state['serviceimpl_egov'].append(res['ServiceImpl']['code'])
            state['serviceimpl_report']['conversion'] = (res['ServiceImpl']['report'])

        self.producer.send_message(topic='agent-res', 
                                    message={'userId': state['user_id'], 'jobId': state['job_id'], 'status': 'SUCCESS', 'description': f"전자정부 표준 프레임워크의 {role} 계층 코드 변환이 완료되었습니다."},
                                    headers=[('AGENT', 'EGOV')])
        
        return state
    
    def converse_vo(self, state):
        parser = JsonOutputParser()

        role = state['next_role']
        print(f"4️⃣ {role} 계층 변환 및 생성:")

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
    
    def get_role_node(state):
        role = state.get("next_role")
        return {
            'controller': 'convert_controller',
            'service': 'convert_service',
            'serviceimpl': 'convert_serviceimpl',
            'vo': 'convert_vo'
        }.get(role, 'complete')  # fallback

    def build_graph(self):
        builder = StateGraph(ConversionEgovState) 

        builder.add_node('complete', self.is_finished)
        builder.add_node('next', self.next_processing)
        builder.add_node('rag', self.search_egov_code)
        builder.add_node('rerank', self.rerank_rag)
        builder.add_node('converse_controller', self.converse_controller)
        builder.add_node('converse_service', self.converse_service)
        builder.add_node('converse_serviceimpl', self.converse_serviceimpl)
        builder.add_node('converse_vo', self.converse_vo)

        builder.add_edge(START, 'complete')
        builder.add_conditional_edges('complete', lambda state: state['next_step'], {'completed': END, 'continue': 'next'})
        builder.add_edge('next', 'rag')
        builder.add_conditional_edges('rag', 
                                      lambda state: 'rerank' if any(len(item) > 0 for item in state.get('retrieved', [])) else state['next_role'], 
                                      {'rerank': 'rerank', 
                                       'controller': 'converse_controller',
                                       'service': 'converse_service',
                                       'serviceimpl': 'converse_serviceimpl',
                                       'vo': 'converse_vo'})
        builder.add_conditional_edges('rerank', lambda x: x['next_role'], {'controller': 'converse_controller',
                                                                           'service': 'converse_service',
                                                                           'serviceimpl': 'converse_serviceimpl',
                                                                           'vo': 'converse_vo'})
        builder.add_edge('converse_controller', 'complete')
        builder.add_edge('converse_service', 'complete')
        builder.add_edge('converse_serviceimpl', 'complete')
        builder.add_edge('converse_vo', 'complete')

        graph = builder.compile()
        # print(graph.get_graph().draw_mermaid())
        # graph.get_graph().draw_mermaid_png(output_file_path='egov_agent.png')
        return graph

if __name__ == '__main__':
    agent = ConversionEgovAgent()
    state = agent.init_state(1, 1)
    graph = agent.build_graph()
    result = graph.invoke(state)
    # with open('testest.json', 'w', encoding='utf-8') as f:
        # json.dump(result, f, ensure_ascii=False, indent=2)