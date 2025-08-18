from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langchain.vectorstores import FAISS
from langchain_core.output_parsers import JsonOutputParser
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

from translate.app.states import ConversionEgovState
from translate.app.producer import MessageProducer
from translate.app.prompts import controller_template, service_prompt, serviceimpl_prompt, vo_prompt
from translate.app.utils import _advance_and_cleanup_finished_features, _is_feature_done, _cleanup_current_feature
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
                    # {*, *_egov, *_report느 백엔드에 보내주기 위한 용도
                    'controller': [],
                    'service': [],
                    'serviceimpl': [],  
                    'vo': [],

                    'controller_egov': [],
                    'service_egov': [],
                    'serviceimpl_egov': [],
                    'vo_egov': [],

                    'controller_report': {'conversion': [], 'generation': []},
                    'service_report': {'conversion': [], 'generation': []},
                    'serviceimpl_report': {'conversion': [], 'generation': []},
                    'vo_report': {'conversion': [], 'generation': []},

                    'retrieved': [],
                    'next_role': '',
                    'next_step': '',
                    
                    # 에이전트 내부에서 변환 처리 시 기능 별로 처리할 수 있도록 따로 저장
                    'features': [], # 기능 단위 코드 목록
                    'current_feature_idx': 0 # 현재 처리 중인 기능 인덱스
                }

        with open(path, encoding='utf-8') as f:
            data = json.load(f)

            for feature in data:
                for feature_name, role2code in feature.items():
                    feature = {
                        'name': feature_name,
                        'codes': {'controller': [], 'service': [], 'serviceimpl': [], 'vo': []},
                        'egov':  {'controller': [], 'service': [], 'serviceimpl': [], 'vo': []},
                        'report':{
                            'controller': {'conversion': [], 'generation': []},
                            'service':    {'conversion': [], 'generation': []},
                            'serviceimpl':{'conversion': [], 'generation': []},
                            'vo':         {'conversion': [], 'generation': []},
                        }
                    }
                    for role, codes in role2code.items():
                        role = 'vo' if role == 'dto' else role  # 기존과 동일한 매핑
                        feature['codes'].setdefault(role, [])
                        feature['codes'][role].extend(codes)

                        # state.setdefault(role, [])
                        # state[role].extend(codes)

                    state['features'].append(feature)
                                
        return state

    def is_finished(self, state):
        state['retrieved'] = []
        _advance_and_cleanup_finished_features(state)

        # roles = ['controller', 'service', 'serviceimpl', 'vo']

        # for role in roles:
        #     raw_cnt = len(state.get(role, []) or [])
        #     conv_cnt = len(state.get(f"{role}_egov", []) or [])
        #     if raw_cnt > conv_cnt:  # 아직 변환할 대상이 남아있음
        #         state['next_step'] = 'continue'
        #         return state
        if not state['features']:
            state['next_step'] = 'completed'
            print('0️⃣ 완성 여부 체크:', state['next_step'])
            return state

        # 아직 변환할 대상이 남아있음
        for b in state['features']:
            if any(len(b['codes'][r]) > len(b['egov'][r]) for r in ['controller','service','serviceimpl','vo']):
                state['next_step'] = 'continue'
                return state

        state['next_step'] = 'completed'

        print('1️⃣ 완성 여부 체크:', state['next_step'])
        return state
    
    def next_processing(self, state):
        print(f"2️⃣ 다음 변환할 계층 확인")
        _advance_and_cleanup_finished_features(state)

        # 현재/다음으로 처리할 기능 선택
        start = state.get('current_feature_idx', 0)
        feature_idx = None
        for i in range(start, len(state['features'])):
            b = state['features'][i]
            if any(len(b['codes'][r]) > len(b['egov'][r]) for r in ['controller','service','serviceimpl','vo']):
                feature_idx = i
                break

        if feature_idx is None:
            state['next_step'] = 'completed'
            return state

        state['current_feature_idx'] = feature_idx
        b = state['features'][feature_idx]

        # 기능 안에서의 처리 우선순위: controller → service → serviceimpl → vo
        for role in ['controller','service','serviceimpl','vo']:
            if len(b['codes'][role]) > len(b['egov'][role]):
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

        b = state['features'][state['current_feature_idx']]
        results = []
        for code in b['codes'][role][len(b['egov'][role]):]:  # 아직 변환 안 한 것만
            query = f"[description]\n[role]{role}\n[code]{code}"
            docs = self.retriever.get_relevant_documents(query)
            cands = [d.page_content for d in docs if d.metadata.get('type','').lower()==role]
            results.append(cands if cands else [])
        
        state['retrieved'] = results

        return state
    
    def rerank_rag(self, state):
        print(f"4️⃣ 검색 결과 rerank")
        role = state.get('next_role')
        b = state['features'][state['current_feature_idx']]

        results = []
        pending_codes = b['codes'][role][len(b['egov'][role]):]
        for i, code in enumerate(pending_codes):
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

        chain = controller_template | self.llm | parser

        current_feature_idx = state['current_feature_idx']
        b = state['features'][current_feature_idx]
        print(f"4️⃣ {b['name']} 기능/{role} 계층 계층 변환 및 생성:")

        # 아직 변환 안 된 코드만 처리
        start_idx = len(b['egov'][role])
        pending = b['codes'][role][start_idx:]
        
        svc_ctx = '\n'.join(f'=== Service class {i+1} ===\n{c}' for i, c in enumerate(b['codes']['service'])) if b['codes']['service'] else ''

        for idx, code in enumerate(pending):
            res = chain.invoke({'INPUT_CONTROLLER_CODE': code,
                                'INPUT_SERVICE_CODE': svc_ctx,
                                'EGOV_EXAM_CODE': state['retrieved'][idx] if idx < len(state['retrieved']) else ''})
            
            # features에 추가
            b['egov']['controller'].append(res['Controller']['code'])
            b['report']['controller']['conversion'].append(res['Controller']['report'])

            # 같은 기능에서 생성되는 Service/VO가 있으면 features 안에만 채움
            if not b['codes']['service']:
                b['codes']['service'].append(res['Service']['code'])
                b['report']['service']['generation'].append(res['Service']['report'])
            if not b['codes']['vo']:
                b['codes']['vo'].append(res['VO']['code'])
                b['report']['vo']['generation'].append(res['VO']['report'])

            ## 백엔드에 보내는 데이터
            state['controller_egov'].append(res['Controller']['code'])
            state['controller_report']['conversion'].append(res['Controller']['report'])

            if not state['service']:
                state['service'].append(res['Service']['code'])
                state['service_report']['generation'].append(res['Service']['report'])

            if not state['vo']:
                state['vo'].append(res['VO']['code'])
                state['vo_report']['generation'].append(res['VO']['report'])
        
        if current_feature_idx < len(state.get('features', [])) and _is_feature_done(state['features'][current_feature_idx]):
            _cleanup_current_feature(state) 

        self.producer.send_message(topic='agent-res', 
                                    message={'userId': state['user_id'], 'jobId': state['job_id'], 'status': 'SUCCESS', 'description': f"전자정부 표준 프레임워크의 {role} 계층 코드 변환이 완료되었습니다."},
                                    headers=[('AGENT', 'EGOV')])
        
        return state
    
    def converse_service(self, state):
        parser = JsonOutputParser()

        role = state['next_role']

        chain = service_prompt | self.llm | parser

        current_feature_idx = state['current_feature_idx']
        b = state['features'][current_feature_idx]
        print(f"4️⃣ {b['name']} 기능/{role} 계층 계층 변환 및 생성:")

        start_idx = len(b['egov'][role])
        pending = b['codes'][role][start_idx:]

        ctrl_ctx = '\n'.join(f'=== Controller {i+1} ===\n{c}' for i, c in enumerate(b['codes']['controller'])) if b['codes']['controller'] else ''

        for idx, code in enumerate(pending):
            res = chain.invoke({'INPUT_SERVICE_CODE': code,
                                'INPUT_CONTROLLER_CODE': ctrl_ctx,
                                'EGOV_EXAM_CODE': state['retrieved'][idx] if idx < len(state['retrieved']) else ''})
            
            # features에 추가
            b['egov']['service'].append(res['Service']['code'])
            b['report']['service']['conversion'].append(res['Service']['report'])

            # 같은 기능에서 생성되는 ServiceImpl 있으면 features 안에만 채움
            if not b['codes']['serviceimpl']:
                b['codes']['serviceimpl'].append(res['ServiceImpl']['code'])
                b['report']['serviceimpl']['generation'].append(res['ServiceImpl']['report'])
                
            ## 백엔드에 보내는 데이터
            state['service_egov'].append(res['Service']['code'])
            state['service_report']['conversion'].append(res['Service']['report'])
            
            if not state['serviceimpl']:
                state['serviceimpl'].append(res['ServiceImpl']['code'])
                state['serviceimpl_report']['generation'].append(res['ServiceImpl']['report'])

        if current_feature_idx < len(state.get('features', [])) and _is_feature_done(state['features'][current_feature_idx]):
            _cleanup_current_feature(state) 

        self.producer.send_message(topic='agent-res', 
                                    message={'userId': state['user_id'], 'jobId': state['job_id'], 'status': 'SUCCESS', 'description': f"전자정부 표준 프레임워크의 {role} 계층 코드 변환이 완료되었습니다."},
                                    headers=[('AGENT', 'EGOV')])
        
        return state
    
    def converse_serviceimpl(self, state):
        parser = JsonOutputParser()

        role = state['next_role']

        chain = serviceimpl_prompt | self.llm | parser

        current_feature_idx = state['current_feature_idx']
        b = state['features'][current_feature_idx]
        print(f"4️⃣ {b['name']} 기능/{role} 계층 계층 변환 및 생성:")

        start_idx = len(b['egov'][role])
        pending = b['codes'][role][start_idx:]
        for idx, code in enumerate(pending):
            res = chain.invoke({'INPUT_SERVICEIMPL_CODE': code,
                                'EGOV_EXAM_CODE': state['retrieved'][idx] if idx < len(state['retrieved']) else ''})

            # features에 추가
            b['egov']['serviceimpl'].append(res['ServiceImpl']['code'])
            b['report']['serviceimpl']['conversion'].append(res['ServiceImpl']['report'])

            ## 백엔드에 보내는 데이터
            state['serviceimpl_egov'].append(res['ServiceImpl']['code'])
            state['serviceimpl_report']['conversion'].append(res['ServiceImpl']['report'])

        if current_feature_idx < len(state.get('features', [])) and _is_feature_done(state['features'][current_feature_idx]):
            _cleanup_current_feature(state) 

        self.producer.send_message(topic='agent-res', 
                                    message={'userId': state['user_id'], 'jobId': state['job_id'], 'status': 'SUCCESS', 'description': f"전자정부 표준 프레임워크의 {role} 계층 코드 변환이 완료되었습니다."},
                                    headers=[('AGENT', 'EGOV')])
        
        return state
    
    def converse_vo(self, state):
        parser = JsonOutputParser()

        role = state['next_role']

        chain = vo_prompt | self.llm | parser

        current_feature_idx = state['current_feature_idx']
        b = state['features'][current_feature_idx]
        print(f"4️⃣ {b['name']} 기능/{role} 계층 계층 변환 및 생성:")

        start_idx = len(b['egov'][role])
        pending = b['codes'][role][start_idx:]
        for idx, code in enumerate(pending):
            res = chain.invoke({'INPUT_DTO_CODE': code,
                                'EGOV_EXAM_CODE': state['retrieved'][idx] if idx < len(state['retrieved']) else ''})

            # features에 추가
            b['egov']['vo'].append(res['VO']['code'])
            b['report']['vo']['conversion'].append(res['VO']['report'])

            ## 백엔드에 보내는 데이터
            state['vo_egov'].append(res['VO']['code'])
            state['vo_report']['conversion'].append(res['VO']['report'])

        if current_feature_idx < len(state.get('features', [])) and _is_feature_done(state['features'][current_feature_idx]):
            _cleanup_current_feature(state) 

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
    result = graph.invoke(state, config={"recursion_limit": 1000})
    with open('testest2.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)