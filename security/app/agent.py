import openai
from langchain.chat_models import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

class State(TypedDict):
    message: str

def test_node(state: State):
    print(state)
    return {'message': '요청 완료'}

def preprocessing():
    pass

def analyze_security():
    pass

def has_vulnerability():
    pass

def retrieve():
    pass

def recommend_security_solution():
    pass

def report():
    pass

def check_vulnerability():
    # 취약점이 있는 경우 rag, 없는 경우 report 노드로 이동하도록 return 수정
    return 'rag'

# 그래프 생성
def build_agent():
    builder = StateGraph(State)

    builder.add_node('preprocessing', preprocessing)
    builder.add_node('analyze', analyze_security)
    builder.add_node('vulnerability', has_vulnerability)
    builder.add_node('rag', retrieve)
    builder.add_node('recommend', recommend_security_solution)
    builder.add_node('report', report)

    builder.add_edge(START, 'preprocessing')
    builder.add_edge('preprocessing', 'analyze')
    builder.add_edge('analyze', 'vulnerability')
    builder.add_conditional_edges('vulnerability', check_vulnerability, {'rag': 'rag', 'report': 'report'})
    builder.add_edge('rag', 'recommend')
    builder.add_edge('recommend', 'report')
    builder.add_edge('report', END)

    graph = builder.compile()
    
    # graph.get_graph().draw_mermaid_png(output_file_path='test.png')

    return graph

if __name__ == '__main__':
    graph = build_agent()
    graph.invoke({'message': 'test'})