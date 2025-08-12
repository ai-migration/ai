from dotenv import load_dotenv
import os
from confluent_kafka import Consumer, KafkaException
import json
from log import Logger
from conversion_egov import ConversionEgovAgent
from states import CoversionEgovState

load_dotenv()

class MessageConsumer:
    def __init__(self):
        self.logger = Logger(name='translate').logger
        self.broker = os.environ.get('KAFKA_SERVER')
        self.topic = os.environ.get('CONS_TOPIC')
        self.group_id = os.environ.get('GROUP_ID')
        self.auto_offset_reset = os.environ.get('AUTO_OFFSET_RESET')
        self.consumer = Consumer({
                                    'bootstrap.servers': self.broker,
                                    'group.id': self.group_id, # consumer의 id
                                    'auto.offset.reset': self.auto_offset_reset  # 처음 실행시 가장 마지막 offset부터
                                })
        self.consumer.subscribe([self.topic])

    def consume(self):
        try:
            print(f"start consume: {self.topic}")

            while True:
                message = self.consumer.poll(1.0)
                if message is None:
                    continue
                if message.error():
                    print(f"Kafka error: {message.error()}")
                else:
                    self.handle_message(message)
        except KafkaException as e:
            self.logger.error(e)
        finally:
            self.consumer.close()

    def handle_message(self, message):
        try:
            request = json.loads(message.value().decode('utf-8'))

            self.logger.info(f"{message.topic()} | key: {message.key()} | value: {request}")
            
            
            # # TO-BE: 메세지에서 파일 내용 받도록 바꾸기
            # state = CoversionEgovState(input_path={'controller': [r'C:\Users\User\Desktop\dev\project\BoardController.java'],
            #                                         'serviceimpl': [r'C:\Users\User\Desktop\dev\project\BoardService.java'],
            #                                         'vo': [r'C:\Users\User\Desktop\dev\project\BoardUpdateDto.java']},
            #                     controller=[],
            #                     controller_egov=[],
            #                     service=[],
            #                     service_egov=[],
            #                     serviceimpl=[],
            #                     serviceimpl_egov=[],
            #                     vo=[],
            #                     vo_egov=[],
            #                     validate='',
            #                     retrieved=[],
            #                     next_role='',
            #                     next_step='',
            #                     controller_report={},
            #                     service_report={},
            #                     serviceimpl_report={},
            #                     vo_report={})
            # agent = ConversionEgovAgent()
            # graph = agent.build_graph()
            # graph.invoke(state)

        except Exception as e:
            self.logger.exception(e)

if __name__ == '__main__':
    consumer = MessageConsumer()
    consumer.consume()