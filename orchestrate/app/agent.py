import openai
from langchain.chat_models import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from producer import MessageProducer
from domain import ToTranslator, ToAuditor
from dataclasses import asdict

producer = MessageProducer()

class State(TypedDict):
    message: str

def call_agent(request):
    print(request)
    '''
    request: {'eventType': 'ConversionRequested', 'timestamp': 1754745245253, 'id': 4, 'userId': 1000, 'filePath': None, 'inputeGovFrameVer': '3.8', 'outputeGovFrameVer': '3.10', 'isTestCode': True, 'conversionType': 'CODE'}
    '''
    if request['eventType'] == 'ConversionRequested':
        producer.send_message('conversion', message=asdict(ToTranslator(id=request['id'],
                                                                        user_id=request['userId'],
                                                                        file_path=request['filePath'],
                                                                        input_egov_frame_ver=request['inputeGovFrameVer'],
                                                                        output_egov_frame_ver=request['outputeGovFrameVer'],
                                                                        is_test_code=request['isTestCode'],
                                                                        conversion_type=request['conversionType'])))
    elif request['agentName'] == 'SecurityRequested':
        producer.send_message('security', asdict(ToAuditor(id=request['id'])))
    elif request['agentName'] == 'ChatbotRequested':
        producer.send_message('chatbot', asdict(ToAuditor(id=request['id'])))



if __name__ == '__main__':
    # graph = build_agent()
    # graph.invoke({'message': 'test'})
    call_agent({"id":1,"agentName":"TRANSLATOR"})