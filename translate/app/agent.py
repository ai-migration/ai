from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from producer import MessageProducer
from translate.app.states import State
from langgraph.prebuilt import ToolNode
import os
from conversion_egov import ConversionEgovAgent

from translate.app.nodes.analyze import analyze_python, analyze_java
from translate.app.nodes.detect import detect_language, select_lang
from translate.app.nodes.preprocess import preprocessing

LLM = 'gpt-4o-mini'
os.environ['OPENAI_API_KEY'] = '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'

class ConversionAgent:
    def __init__(self):
        self.llm = ChatOpenAI(model=LLM)
        self.producer = MessageProducer()
        self.converion_egov_agent = ConversionEgovAgent()

    def report(self):
        pass

    def build_graph(self):
        builder = StateGraph(State)

        builder.add_node('preprocessing', preprocessing)
        builder.add_node('detect', detect_language)
        builder.add_node('analyze_python', analyze_python)
        builder.add_node('analyze_java', analyze_java)
        # builder.add_node('conversion_python_to_java', conversion_python_to_java)
        builder.add_node('conversion_egov', self.converion_egov_agent.build_graph())
        builder.add_node('report', self.report)

        builder.add_edge(START, 'preprocessing')
        builder.add_edge('preprocessing', 'detect')
        builder.add_conditional_edges('detect', select_lang, {'python': 'analyze_python', 'java': 'analyze_java'})
        # builder.add_edge('analyze_python', 'conversion_python_to_java')
        builder.add_edge('analyze_java', 'conversion_egov')
        # builder.add_edge('conversion_python_to_java', 'conversion_egov')
        builder.add_edge('conversion_egov', 'report')
        builder.add_edge('report', END)

        graph = builder.compile()
        graph.get_graph().draw_mermaid_png(output_file_path='main_agent.png')
        return graph

if __name__ == '__main__':
    agent = ConversionAgent()
    graph = agent.build_graph()
    graph.invoke()