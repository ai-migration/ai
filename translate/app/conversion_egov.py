from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langgraph.graph import StateGraph, START, END
from producer import MessageProducer
from states import CoversionEgovState
from langchain.vectorstores import FAISS
from langchain_core.output_parsers import JsonOutputParser
from prompts import controller_template, service_prompt, serviceimpl_prompt, vo_prompt
import json

LLM = 'gpt-4o-mini'
EMBEDDING = 'text-embedding-3-small'
DB_PATH = 'eGovCodeDB_0805'

class ConversionEgovAgent:
    def __init__(self):
        self.llm = ChatOpenAI(model=LLM)
        self.embedding =  OpenAIEmbeddings(model=EMBEDDING)
        vectordb = FAISS.load_local(DB_PATH, embeddings=self.embedding, allow_dangerous_deserialization=True)
        self.retriever = vectordb.as_retriever(search_kwargs={"k": 3})
        self.producer = MessageProducer()

    def preprocessing(self, state):
        # 파일 읽어서 state 초기화
        role2path = state['input_path']

        for role, paths in role2path.items():
            for p in paths:
                with open(p, encoding='utf-8') as f:
                    code = f.read()
                    state[role].append(code)
        return state

    def is_finished(self, state):
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

            with open("agent_test4.json", "w", encoding='utf-8') as json_file:
                json.dump(state, json_file, ensure_ascii=False, indent=2)
        else:
            state['next_step'] = 'continue'

        print('1️⃣ 완성 여부 체크:', state['next_step'])
        return state
    
    def next_processing(self, state):
        egov_targets = ['controller', 'service', 'serviceimpl', 'vo']
        for role in egov_targets:
            # 변환 대상 코드가 있을 때만 egov 체크
            if state[role]:
                if len(state[role]) != len(state[f"{role}_egov"]):
                    state['next_role'] = role
                    state['next_step'] = 'conversion'
                    print(f"2️⃣ 다음 기능: {state['next_role']} 계층 {state['next_step']}")
                    return state
                
        print(f"2️⃣ 모든 계층 변환 완료")
        return state 

    def search_egov_code(self, state):
        print(f"3️⃣ 유사 코드 검색")
        role = state['next_role']
        results = []
        for code in state[role]:
            query = f"[description]\n[role]{role}\n[code]{code}"

            docs = self.retriever.get_relevant_documents(query)
            role_exam_codes = []
            for i in docs:
                print('✅ 검색된 문서', i.metadata)
                if i.metadata['type'].lower() == role:
                    exam_code = i.page_content.split('[code]')[-1]
                    role_exam_codes.append(exam_code)

            results.append(role_exam_codes[0])

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

        return state
    
    def post_processing(self):
        pass

    def validate(self):
        pass

    def build_graph(self):
        builder = StateGraph(CoversionEgovState) 

        builder.add_node('preprocessing', self.preprocessing)
        builder.add_node('complete', self.is_finished)
        builder.add_node('next', self.next_processing)
        builder.add_node('rag', self.search_egov_code)
        builder.add_node('conversion', self.converse_code)

        builder.add_edge(START, 'preprocessing')
        builder.add_edge('preprocessing', 'complete')
        builder.add_conditional_edges('complete', lambda state: state['next_step'], {'completed': END, 'continue': 'next'})
        builder.add_edge('next', 'rag')
        builder.add_edge('rag', 'conversion')
        builder.add_edge('conversion', 'complete')

        graph = builder.compile()
        # print(graph.get_graph().draw_mermaid())
        # graph.get_graph().draw_mermaid_png(output_file_path='egov_agent.png')
        return graph

    def run(self, graph):
        graph.invoke()
        # invoke -> produce

if __name__ == '__main__':
    state = CoversionEgovState(input_path={'controller': ['BoardController.java'],
    # state = CoversionEgovState(input_path={'controller': [],
                                        #    'serviceimpl': ['BoardService.java'],
                                           'serviceimpl': [],
                                           'vo': []},
                                        #    'vo': ['BoardUpdateDto.java', 'BoardWriteDto.java', 'SearchData.java']},
                                controller=[],
                                controller_egov=[],
                                service=[],
                                service_egov=[],
                                serviceimpl=[],
                                serviceimpl_egov=[],
                                vo=[],
                                vo_egov=[],
                                validate='',
                                retrieved=[],
                                next_role='',
                                next_step='',
                                controller_report={},
                                service_report={},
                                serviceimpl_report={},
                                vo_report={})
    agent = ConversionEgovAgent()
    graph = agent.build_graph()
    graph.invoke(state)