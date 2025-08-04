import openai
from langchain.chat_models import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from producer import MessageProducer
from states import State
from nodes import preprocessing, detect_language, analyze_java, analyze_python, conversion_python_to_java, gen_egov_vo, gen_egov_service, gen_egov_controller, gen_egov_serviceImpl, check_regen, validate, report, post_processing, select_lang, retrieve

producer = MessageProducer()

# 그래프 생성
def build_agent():
    builder = StateGraph(State)

    builder.add_node('preprocessing', preprocessing)
    builder.add_node('detect', detect_language)
    builder.add_node('analyze_python', analyze_python)
    builder.add_node('analyze_java', analyze_java)
    builder.add_node('conversion_python_to_java', conversion_python_to_java)
    builder.add_node('rag', retrieve)
    builder.add_node('gen_egov_vo', gen_egov_vo)
    builder.add_node('gen_egov_service', gen_egov_service)
    builder.add_node('gen_egov_serviceImpl', gen_egov_serviceImpl)
    builder.add_node('gen_egov_controller', gen_egov_controller)
    builder.add_node("post_processing", post_processing)
    builder.add_node('validate', validate)
    builder.add_node('report', report)

    builder.add_edge(START, 'preprocessing')
    builder.add_edge('preprocessing', 'detect')
    builder.add_conditional_edges('detect', select_lang, {'python': 'analyze_python', 'java': 'analyze_java'})
    builder.add_edge('analyze_python', 'conversion_python_to_java')
    builder.add_edge('analyze_java', 'rag')
    builder.add_edge('conversion_python_to_java', 'rag')
    builder.add_edge('rag', 'gen_egov_vo')
    builder.add_edge('gen_egov_vo', 'gen_egov_service')
    builder.add_edge('gen_egov_service', 'gen_egov_serviceImpl')
    builder.add_edge('gen_egov_serviceImpl', 'gen_egov_controller')
    builder.add_edge('gen_egov_controller', 'post_processing')
    builder.add_edge('post_processing', 'validate')
    builder.add_conditional_edges('validate', check_regen, {'reconversion': 'gen_egov_vo'})
    # builder.add_conditional_edges('validate', check_regen, {'vo': 'gen_egov_vo', 'service': 'gen_egov_service', 'serviceImpl': 'gen_egov_serviceImpl', 'controller': 'gen_egov_controller'})
    builder.add_edge('validate', 'report')
    builder.add_edge('report', END)

    graph = builder.compile()
    # graph.get_graph().draw_mermaid_png(output_file_path='test.png')
    return graph

if __name__ == '__main__':
    graph = build_agent()
    graph.invoke({'message': 'test'})