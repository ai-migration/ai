from dotenv import load_dotenv
import os
from confluent_kafka import Consumer, KafkaException
import json
from orchestrate.app.log import Logger
from orchestrate.app.agent import call_agent
from orchestrate.app.producer import MessageProducer
load_dotenv()

class MessageConsumer:
    def __init__(self):
        self.logger = Logger(name='consumer').logger
        self.broker = os.environ.get('KAFKA_SERVER')
        self.topic = os.environ.get('CONS_TOPIC')
        self.group_id = os.environ.get('GROUP_ID')
        self.auto_offset_reset = os.environ.get('AUTO_OFFSET_RESET')
        self.consumer = Consumer({
                                    'bootstrap.servers': self.broker,
                                    'group.id': self.group_id, # consumer의 id
                                    'auto.offset.reset': self.auto_offset_reset,  # 처음 실행시 가장 마지막 offset부터
                                    'max.poll.interval.ms': 1800000
                                })
        self.consumer.subscribe([t for t in self.topic.split(',')])
        self.producer = MessageProducer()

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
                    print("Headers:")
                    if message.headers():
                        for header in message.headers():
                            key, value = header
                            print(f"  {key}: {value.decode('utf-8') if value else None}")
                            
                    self.handle_message(message)
        except KafkaException as e:
            self.logger.error(e)
        finally:
            self.consumer.close()

    def handle_message(self, message):
        try:
            request = json.loads(message.value().decode('utf-8'))

            self.logger.info(f"{message.topic()} | key: {message.key()} | value: {request}")

            if message.topic() == 'java-message':
                call_agent(request)
            elif message.topic() == 'agent-res':
                self.producer.send_message('python-message', request)

                ## 에이전트 별로 처리가 필요할 때 사용
                # if message.headers():
                #     for header in message.headers():
                #         key, value = header
                #         value = value.decode('utf-8') if value else None
                #         if (key, value) == ('AGENT', 'ANALYSIS'):
                #             self.producer.send_message('java', request)
                #         elif (key, value) == ('AGENT', 'EGOV'):
                #             self.producer.send_message('java', request)
                            
                # with open("agent_test5.json", "w", encoding='utf-8') as json_file:
                #     json.dump(request, json_file, ensure_ascii=False, indent=2)

        except Exception as e:
            self.logger.exception(e)

if __name__ == '__main__':
    consumer = MessageConsumer()
    consumer.consume()