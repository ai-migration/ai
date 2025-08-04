import openai
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from producer import MessageProducer
from states import State
from nodes import preprocessing, detect_language, analyze_java, analyze_python, conversion_python_to_java, gen_egov_vo, gen_egov_service, gen_egov_controller, gen_egov_serviceImpl, check_regen, validate, report, post_processing, select_lang, egov_rag
from langchain.vectorstores import FAISS
from langchain.chains import RetrievalQA
from tools import search_egovcode
from langgraph.prebuilt import ToolNode
import os

LLM = 'gpt-4o-mini'
EMBEDDING = 'ext-embedding-3-small'
DB_PATH = 'eGovCodeDB_0804'

class ConversionEgovAgent:
    def __init__(self):
        self.llm = ChatOpenAI(model=LLM)
        self.embedding =  OpenAIEmbeddings(model=EMBEDDING)
        self.retriever = FAISS.load_local(DB_PATH, embeddings=EMBEDDING, allow_dangerous_deserialization=True)
        self.producer = MessageProducer()
        self.state = State

    def preprocessing(self):
        # 파일 읽어서 state 초기화
        pass

    def search_egov_code(self, state):
        query = f"[description]\n[role]{state['role']}\n[code]{state['input_code']}"

        result = [i for i in self.retriever.get_relevant_documents(query) if i.metadata.get('type', '') == state['role']]
        sample_code = result[0].page_content.split('[code]')[-1]

        return sample_code

    def generate_controller(self):
        pass

    def generate_service(self):
        pass

    def generate_serviceImpl(self):
        pass

    def generate_vo(self):
        pass
    
    def check_regen(self):
        pass

    def post_processing(self):
        pass

    def validate(self):
        pass

    def build_graph(self, state):
        builder = StateGraph(state)

        builder.add_node('preprocessing', self.preprocessing)
        builder.add_node('egov_rag', self.search_egov_code)
        builder.add_node('generate_vo', self.generate_vo)
        builder.add_node('generate_service', self.generate_service)
        builder.add_node('generate_serviceImpl', self.generate_serviceImpl)
        builder.add_node('generate_controller', self.generate_controller)
        builder.add_node("post_processing", self.post_processing)
        builder.add_node('validate', self.validate)

        builder.add_edge(START, 'preprocessing')
        builder.add_edge('preprocessing', 'egov_rag')
        builder.add_edge('egov_rag', 'generate_vo')
        builder.add_edge('generate_vo', 'generate_service')
        builder.add_edge('generate_service', 'generate_serviceImpl')
        builder.add_edge('generate_serviceImpl', 'generate_controller')
        builder.add_edge('generate_controller', 'post_processing')
        builder.add_edge('post_processing', 'validate')
        builder.add_conditional_edges('validate', self.check_regen, {'reconversion': 'generate_vo'})
        builder.add_edge('validate', END)

        graph = builder.compile()
        graph.get_graph().draw_mermaid_png(output_file_path='egov_agent.png')
        return graph

    def run(self, graph):
        graph.invoke()
        # invoke -> produce

if __name__ == '__main__':
    agent = ConversionEgovAgent()
    graph = agent.build_graph()