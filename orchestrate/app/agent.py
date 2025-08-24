from typing import TypedDict
from orchestrate.app.producer import MessageProducer
from orchestrate.app.domain import ToTranslator, ToAuditor
from dataclasses import asdict

producer = MessageProducer()

class State(TypedDict):
    message: str

def call_agent(request):
    '''
    request: {'eventType': 'ConversionRequested', 'timestamp': 1755069341605, 'jobId': None, 'userId': 11, 'filePath': None, 'inputeGovFrameVer': '3.8', 'outputeGovFrameVer': '3.10', 'isTestCode': True, 'conversionType': 'CODE'}
    '''
    if request['eventType'] == 'ConversionRequested':
        producer.send_message('conversion', message=asdict(ToTranslator(job_id=request['jobId'],
                                                                        user_id=request['userId'],
                                                                        file_path=request['filePath'],
                                                                        input_egov_frame_ver=request['inputeGovFrameVer'],
                                                                        output_egov_frame_ver=request['outputeGovFrameVer'],
                                                                        is_test_code=request['isTestCode'],
                                                                        conversion_type=request['conversionType'])))
    elif request['eventType'] == 'SecurityRequested':
        producer.send_message('security', asdict(ToAuditor(
                                                           user_id=request['userId'],
                                                           job_id=request['jobId'])))
    elif request['eventType'] == 'ChatbotRequested':
        producer.send_message('chatbot', asdict(ToAuditor(id=request['id'])))



if __name__ == '__main__':
    # graph = build_agent()
    # graph.invoke({'message': 'test'})
    call_agent({"id":1,"agentName":"TRANSLATOR"})